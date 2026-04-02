from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .catalogs import load_level_template_catalog, load_primitive_prefab_catalog
from .common import md5_file, project_root, write_text


OVERRIDDEN_LEVEL_PAK_ENTRIES = {"leveldata.xml", "levelinfo.xml", "mission_mission0.xml"}


def _resolve_template(asset_graph: dict, root: Path) -> dict:
    catalog = load_level_template_catalog(root)
    requested_profile = asset_graph["terrain"]["template_profile"]
    requested_size = asset_graph["world"]["heightmap_size"]
    for template in catalog["templates"]:
        if template["profile"] == requested_profile and template["heightmap_size"] == requested_size:
            if not template.get("available"):
                raise ValueError(
                    f"No checked-in golden template is available for profile={requested_profile} heightmap_size={requested_size}"
                )
            return template
    raise ValueError(f"No level template matches profile={requested_profile} heightmap_size={requested_size}")


def _level_editor_size(heightmap_size: int) -> int:
    return (heightmap_size * 25) // 64


def _format_csv(values: list[float]) -> str:
    rendered: list[str] = []
    for value in values:
        if float(value).is_integer():
            rendered.append(str(int(value)))
        else:
            rendered.append(f"{value:.6f}".rstrip("0").rstrip("."))
    return ",".join(rendered)


def _level_file_xml(asset_graph: dict, main_layer_guid: str) -> str:
    world = asset_graph["world"]
    center = world["heightmap_size"] / 2
    viewer_z = asset_graph["spawn"]["transform"]["position"][2]
    return "\n".join(
        [
            '<Level WaterColor="16711680" SandboxVersion="5.6.5.30">',
            f' <View ViewerPos="{center:.3f},{center:.3f},{viewer_z:.3f}" ViewerAngles="0,-0,0"/>',
            ' <Fog Fog="" Terrain="" EnvState="" VolFogShadows="" VolumetricCloud="" SkyBox="" Ocean="" OceanAnimation="" DynTexSource=""/>',
            ' <Missions Current="Mission0">',
            '  <Mission Name="Mission0" Description="" PlayerEquipPack="" Script="" MissionTime="12:00">',
            f'   <ObjectLayers LayerVersion="2" Current="Main" CurrentGUID="{main_layer_guid}"/>',
            "   <Objects />",
            f'   <Lighting SunRotation="{asset_graph["lighting"]["sun_rotation"]}" SunHeight="{asset_graph["lighting"]["sun_height"]}" Algorithm="3" Lighting="1" Shadows="1" ShadowIntensity="100" ILQuality="1" HemiSamplQuality="5" Longitude="90" DawnTime="355" DawnDuration="10" DuskTime="365" DuskDuration="10" SunVector="{asset_graph["lighting"]["sun_vector"]}"/>',
            "   <Weapons>",
            "    <Used />",
            "    <Ammo />",
            "   </Weapons>",
            f'   <MiniMap CenterX="{world["heightmap_size"] // 2}" CenterY="{world["heightmap_size"] // 2}" ExtendsX="{world["heightmap_size"] // 2}" ExtendsY="{world["heightmap_size"] // 2}" TexWidth="1024" TexHeight="1024"/>',
            "  </Mission>",
            " </Missions>",
            " <EntityPrototypesLibs>",
            '  <LevelLibrary Name="Level"/>',
            " </EntityPrototypesLibs>",
            " <ParticleLibs>",
            '  <LevelLibrary Name="Level" SandboxVersion="5.6.5.30"/>',
            " </ParticleLibs>",
            " <FlareLibs>",
            '  <LevelLibrary Name="Level"/>',
            " </FlareLibs>",
            "</Level>",
            "",
        ]
    )


def _levelinfo_xml(asset_graph: dict) -> str:
    world = asset_graph["world"]
    editor_size = _level_editor_size(world["heightmap_size"])
    return "\n".join(
        [
            f'<LevelInfo SandboxVersion="5.6.5.30" Name="assets/levels/{escape(asset_graph["slug"])}" HeightmapSize="{editor_size}">',
            f' <TerrainInfo HeightmapSize="{world["heightmap_size"]}" UnitSize="{world["unit_size"]}" SectorSize="{world["sector_size"]}" SectorsTableSize="{world["heightmap_size"] // world["sector_size"]}" HeightmapZRatio="{world["heightmap_z_ratio"]}" OceanWaterLevel="{world["ocean_water_level"]}"/>',
            " <Missions>",
            '  <Mission Name="Mission0" Description=""/>',
            " </Missions>",
            "</LevelInfo>",
            "",
        ]
    )


def _leveldata_xml(asset_graph: dict) -> str:
    world = asset_graph["world"]
    editor_size = _level_editor_size(world["heightmap_size"])
    return "\n".join(
        [
            '<LevelData SandboxVersion="5.6.5.30">',
            f' <LevelInfo CreationDate="03/29/26" Name="{escape(asset_graph["slug"])}" HeightmapSize="{editor_size}" HeightmapUnitSize="{world["unit_size"]}" HeightmapMaxHeight="{world["max_height"]}" WaterLevel="{world["ocean_water_level"]}" TerrainSectorSizeInMeters="{world["sector_size"]}"/>',
            " <SurfaceTypes>",
            '  <SurfaceType Name="%ENGINE%/EngineAssets/Materials/material_terrain_default" SurfaceTypeID="0" DetailTexture="" DetailScaleX="1" DetailScaleY="1" DetailMaterial="%ENGINE%/EngineAssets/Materials/material_terrain_default" ProjectAxis="2" Bumpmap="" ProjAxis="Z"/>',
            " </SurfaceTypes>",
            " <CollisionClasses>",
            '  <CollisionClass type="0" ignore="0"/>',
            " </CollisionClasses>",
            " <Layers>",
            '  <Layer Name="Main" Parent="" Id="1" Specs="7"/>',
            '  <Layer Name="Terrain" Parent="" Id="2" Specs="7"/>',
            " </Layers>",
            " <Vegetation />",
            " <MaterialsLibrary>",
            '  <Library Name="Level"/>',
            " </MaterialsLibrary>",
            " <ParticlesLibrary />",
            " <GameTokensLibraryReferences />",
            "</LevelData>",
            "",
        ]
    )


def _environment_xml() -> str:
    return "\n".join(
        [
            "<Environment>",
            ' <Fog ViewDistance="8000" ViewDistanceLowSpec="1000" LDRGlobalDensMult="1.0"/>',
            ' <Terrain DetailLayersViewDistRatio="1.0" HeightMapAO="0" IntegrateObjects="0" AutoGenerateBaseTexture="0" SupportOfflineProceduralVegetation="0"/>',
            ' <EnvState ConsoleMergedMeshesPool="2750" ShowTerrainSurface="1" SunShadowsMinSpec="1" SunShadowsAdditionalCascadeMinSpec="0" SunShadowsClipPlaneRange="256.0f" SunShadowsClipPlaneRangeShift="0.0f" SunShadowsFromTerrain="0" UseLayersActivation="0"/>',
            ' <VolFogShadows Enable="0" EnableForClouds="0"/>',
            ' <VolumetricCloud HorizonHeight="-1000.0" MaxViewableDistance="100000.0" MaxRayMarchDistance="20000.0" ShadingLOD="0.7" ShadowTilingSize="16000" MaxGlobalCloudDensity="0.04" GlobalCloudNoiseVolumeTexture="" GlobalCloudNoiseScale="3,3,5" EdgeTurbulenceNoiseVolumeTexture="" EdgeTurbulenceNoiseScale="1,1,1" EdgeTurbulenceNoiseErode="1" EdgeTurbulenceNoiseAbsolute="1" CloudVolumeTexture="" TilingSize="64000,64000,4000" TilingOffset="0,0,0" RemapCloudDensityMin="0.0" RemapCloudDensityMax="1.0" AdditionalNoiseIntensity="0.2"/>',
            ' <Ocean Material="%ENGINE%/EngineAssets/Materials/Water/Ocean_default" CausticDepth="8.0" CausticIntensity="1.0" CausticsTilling="1.0"/>',
            ' <OceanAnimation WindDirection="1.0" WindSpeed="4.0" WavesAmount="1.5" WavesSize="0.4"/>',
            ' <DynTexSource Width="256" Height="256"/>',
            "</Environment>",
            "",
        ]
    )


def _timeofday_xml(asset_graph: dict) -> str:
    lighting = asset_graph["lighting"]
    return "\n".join(
        [
            f'<TimeOfDay Time="{lighting["time_hour"]}" TimeStart="0" TimeEnd="24" TimeAnimSpeed="0">',
            " <Presets>",
            f'  <Preset Name="{lighting["preset"]}" Default="1"/>',
            " </Presets>",
            "</TimeOfDay>",
            "",
        ]
    )


def _mission_xml(asset_graph: dict) -> str:
    world = asset_graph["world"]
    lighting = asset_graph["lighting"]
    center = world["heightmap_size"] // 2
    return "\n".join(
        [
            '<Mission Name="Mission0" Description="" Time="12:00" PlayerEquipPack="" Script="" CGFCount="0">',
            " <Environment>",
            '  <Fog ViewDistance="8000" ViewDistanceLowSpec="1000" LDRGlobalDensMult="1.0"/>',
            '  <Terrain DetailLayersViewDistRatio="1.0" HeightMapAO="0" IntegrateObjects="0" AutoGenerateBaseTexture="0" SupportOfflineProceduralVegetation="0"/>',
            '  <EnvState ConsoleMergedMeshesPool="2750" ShowTerrainSurface="1" SunShadowsMinSpec="1" SunShadowsAdditionalCascadeMinSpec="0" SunShadowsClipPlaneRange="256.0f" SunShadowsClipPlaneRangeShift="0.0f" SunShadowsFromTerrain="0" UseLayersActivation="0" SunLinkedToTOD="1"/>',
            '  <VolFogShadows Enable="0" EnableForClouds="0"/>',
            '  <VolumetricCloud HorizonHeight="-1000.0" MaxViewableDistance="100000.0" MaxRayMarchDistance="20000.0" ShadingLOD="0.7" ShadowTilingSize="16000" MaxGlobalCloudDensity="0.04" GlobalCloudNoiseVolumeTexture="" GlobalCloudNoiseScale="3,3,5" EdgeTurbulenceNoiseVolumeTexture="" EdgeTurbulenceNoiseScale="1,1,1" EdgeTurbulenceNoiseErode="1" EdgeTurbulenceNoiseAbsolute="1" CloudVolumeTexture="" TilingSize="64000,64000,4000" TilingOffset="0,0,0" RemapCloudDensityMin="0.0" RemapCloudDensityMax="1.0" AdditionalNoiseIntensity="0.2"/>',
            '  <SkyBox Material="%ENGINE%/EngineAssets/Materials/Sky/Sky" MaterialLowSpec="%ENGINE%/EngineAssets/Materials/Sky/Sky" Angle="0" Stretching="0.5"/>',
            '  <Ocean Material="%ENGINE%/EngineAssets/Materials/Water/Ocean_default" CausticDepth="8.0" CausticIntensity="1.0" CausticsTilling="1.0"/>',
            '  <OceanAnimation WindDirection="1.0" WindSpeed="4.0" WavesAmount="1.5" WavesSize="0.4"/>',
            '  <DynTexSource Width="256" Height="256"/>',
            f'  <Lighting SunRotation="{lighting["sun_rotation"]}" SunHeight="{lighting["sun_height"]}" Algorithm="3" Lighting="1" Shadows="1" ShadowIntensity="100" ILQuality="1" HemiSamplQuality="5" Longitude="90" DawnTime="355" DawnDuration="10" DuskTime="365" DuskDuration="10" SunVector="{lighting["sun_vector"]}"/>',
            " </Environment>",
            f' <TimeOfDay Time="{lighting["time_hour"]}" TimeStart="{lighting["time_hour"]}" TimeEnd="{lighting["time_hour"]}" TimeAnimSpeed="0">',
            "  <Presets>",
            f'   <Preset Name="{lighting["preset"]}" Default="1"/>',
            "  </Presets>",
            " </TimeOfDay>",
            f' <MiniMap CenterX="{center}" CenterY="{center}" ExtendsX="{center}" ExtendsY="{center}" TexWidth="1024" TexHeight="1024"/>',
            " <Weapons>",
            "  <Used />",
            "  <Ammo />",
            " </Weapons>",
            " <Objects />",
            "</Mission>",
            "",
        ]
    )


def _terrain_texture_xml(asset_graph: dict) -> str:
    tile_count = max(1, asset_graph["world"]["heightmap_size"] // 256)
    rows = [f'   <tile X="{x}" Y="{y}" Size="512"/>' for y in range(tile_count) for x in range(tile_count)]
    return "\n".join(
        [
            f'<TerrainTexture TileCountX="{tile_count}" TileCountY="{tile_count}" TileResolution="512">',
            " <RGBLayer>",
            "  <Tiles>",
            *rows,
            "  </Tiles>",
            " </RGBLayer>",
            "</TerrainTexture>",
            "",
        ]
    )


def _brush_object_xml(placement: dict, layer_name: str, layer_guid: str, prefab_path: str) -> str:
    transform = placement["transform"]
    material_attribute = ""
    if placement.get("material_override"):
        material_attribute = f' Material="{escape(placement["material_override"])}"'
    return (
        f'   <Object Type="Brush" Layer="{escape(layer_name)}" LayerGUID="{layer_guid}" Id="{uuid.uuid4()}" '
        f'Name="{escape(placement["name"])}" Pos="{_format_csv(transform["position"])}" '
        f'Rotate="{_format_csv(transform["rotation"])}" Scale="{_format_csv(transform["scale"])}" '
        f'ColorRGB="16777215" UseCustomLevelLayerColor="0" MinSpec="0" MatLayersMask="0" '
        f'Prefab="{escape(prefab_path)}"{material_attribute} IgnoreVisareas="0" CastShadowMaps="1" '
        f'GIMode="1" RainOccluder="1" SupportSecondVisarea="0" DynamicDistanceShadows="0" Hideable="0" '
        f'LodRatio="100" ViewDistRatio="100" ExcludeFromNavigation="0" NoDynamicWater="0" AIRadius="-1" '
        f'NoStaticDecals="0" RecvWind="0" Occluder="0" DrawLast="0" ShadowLodBias="0" '
        f'IgnoreTerrainLayerBlend="0" IgnoreDecalBlend="0" RndFlags="0" OutdoorOnly="0" CollisionFiltering="0"/>'
    )


def _layer_xml(name: str, layer_type: int, guid: str, body_lines: list[str]) -> str:
    lines = [
        "<ObjectLayer>",
        f' <Layer Name="{name}" FullName="{name}" GUID="{guid}" Hidden="0" Frozen="0" Expanded="0" Type="{layer_type}" Exportable="1" ExportLayerPak="1" DefaultLoaded="0" HavePhysics="1" IsDefaultColor="1" Color="4671303" Timestamp="1777777777">',
        *body_lines,
        " </Layer>",
        "</ObjectLayer>",
        "",
    ]
    return "\n".join(lines)


def _main_layer_xml(asset_graph: dict, main_layer_guid: str, root: Path) -> str:
    primitive_catalog = {item["name"]: item["asset_path"] for item in load_primitive_prefab_catalog(root)["prefabs"]}
    body_lines = ["  <LayerObjects>"]
    for placement in asset_graph["placements"]:
        prefab_path = primitive_catalog.get(placement["ref"], placement["ref"])
        body_lines.append(_brush_object_xml(placement, placement["layer"], main_layer_guid, prefab_path))
    body_lines.append("  </LayerObjects>")
    return _layer_xml("Main", 0, main_layer_guid, body_lines)


def _terrain_layer_xml(terrain_layer_guid: str) -> str:
    return _layer_xml(
        "Terrain",
        2,
        terrain_layer_guid,
        [
            "  <Files>",
            '   <File path="LevelData/Heightmap.dat"/>',
            '   <File path="LevelData/TerrainTexture.xml"/>',
            '   <File path="TerrainTexture.pak"/>',
            "  </Files>",
        ],
    )


def _cryasset_xml(asset_graph: dict) -> str:
    slug = asset_graph["slug"]
    return "\n".join(
        [
            f'<AssetMetadata version="0" type="Level" guid="{uuid.uuid4()}" source="" timestamp="1777777777">',
            " <Files>",
            f'  <File path="{slug}/{slug}.level"/>',
            " </Files>",
            " <Dependencies>",
            '  <Path usageCount="1">%ENGINE%/EngineAssets/Shading/default.env</Path>',
            "  <Path>%editor%/crydesigner_timeofday.xml</Path>",
            "  <Path>%editor%/default_time_of_day.xml</Path>",
            "  <Path>%editor%/leveltemplates.xml</Path>",
            "  <Path>%editor%/mapscreenshotsettings.xml</Path>",
            "  <Path>%editor%/mbttemplates.xml</Path>",
            "  <Path>%editor%/modellingpanel.xml</Path>",
            "  <Path>%editor%/objecttemplates.xml</Path>",
            "  <Path>%editor%/propertyenumerations.xml</Path>",
            "  <Path>%editor%/soundtemplates.xml</Path>",
            "  <Path>%editor%/toolbox.xml</Path>",
            "  <Path>%editor%/usertools.xml</Path>",
            "  <Path>%engine%/engineassets/materials/fog/fogvolumebox.mtl</Path>",
            "  <Path>%engine%/engineassets/materials/fog/fogvolumeellipsoid.mtl</Path>",
            "  <Path>%engine%/engineassets/materials/material_terrain_default.mtl</Path>",
            "  <Path>%engine%/engineassets/materials/sky/sky.mtl</Path>",
            "  <Path>%engine%/engineassets/materials/water/ocean_default.mtl</Path>",
            " </Dependencies>",
            "</AssetMetadata>",
            "",
        ]
    )


def build_level_job(stage_assets_root: Path, asset_graph: dict, root: Path | None = None) -> dict:
    repo_root = root or project_root()
    template = _resolve_template(asset_graph, repo_root)
    template_level_root = repo_root / template["source_level_dir"]
    level_root = stage_assets_root / "Assets" / "levels" / asset_graph["slug"]
    level_root.mkdir(parents=True, exist_ok=True)
    (level_root / "layers").mkdir(exist_ok=True)
    (level_root / "leveldata").mkdir(exist_ok=True)

    shutil.copy2(template_level_root / "leveldata" / "heightmap.dat", level_root / "leveldata" / "heightmap.dat")
    shutil.copy2(template_level_root / "leveldata" / "vegetationmap.dat", level_root / "leveldata" / "vegetationmap.dat")
    shutil.copy2(template_level_root / "terraintexture.pak", level_root / "terraintexture.pak")

    main_layer_guid = str(uuid.uuid4())
    terrain_layer_guid = str(uuid.uuid4())
    write_text(level_root / f'{asset_graph["slug"]}.level', _level_file_xml(asset_graph, main_layer_guid))
    write_text(level_root / "leveldata" / "environment.xml", _environment_xml())
    write_text(level_root / "leveldata" / "timeofday.xml", _timeofday_xml(asset_graph))
    write_text(level_root / "leveldata" / "terraintexture.xml", _terrain_texture_xml(asset_graph))
    write_text(level_root / "leveldata" / "gametokens.xml", "<GameTokens />\n")
    write_text(level_root / "leveldata" / "objectives.xml", "<Objectives />\n")
    write_text(level_root / "layers" / "main.lyr", _main_layer_xml(asset_graph, main_layer_guid, repo_root))
    write_text(level_root / "layers" / "terrain.lyr", _terrain_layer_xml(terrain_layer_guid))

    template_level_pak = template_level_root / "level.pak"
    level_pak = level_root / "level.pak"
    with zipfile.ZipFile(template_level_pak) as source_archive, zipfile.ZipFile(level_pak, "w", zipfile.ZIP_DEFLATED) as target_archive:
        for name in sorted(source_archive.namelist()):
            if name in OVERRIDDEN_LEVEL_PAK_ENTRIES:
                continue
            target_archive.writestr(name, source_archive.read(name))
        target_archive.writestr("leveldata.xml", _leveldata_xml(asset_graph))
        target_archive.writestr("levelinfo.xml", _levelinfo_xml(asset_graph))
        target_archive.writestr("mission_mission0.xml", _mission_xml(asset_graph))

    filelist = "\n".join(
        [
            f'<download name="{asset_graph["slug"]}" type="Map">',
            ' <index src="filelist.xml" dest="filelist.xml"/>',
            " <files>",
            f'  <file src="level.pak" dest="level.pak" size="{level_pak.stat().st_size}" md5="{md5_file(level_pak)}"/>',
            " </files>",
            "</download>",
            "",
        ]
    )
    write_text(level_root / "filelist.xml", filelist)
    write_text(stage_assets_root / "Assets" / "levels" / f'{asset_graph["slug"]}.level.cryasset', _cryasset_xml(asset_graph))

    return {
        "asset_kind": "level",
        "template_id": template["template_id"],
        "published_assets_root": f'Assets/levels/{asset_graph["slug"]}',
        "level_root": level_root.as_posix(),
        "placements_compiled": len(asset_graph["placements"]),
        "files": [
            f'Assets/levels/{asset_graph["slug"]}/{asset_graph["slug"]}.level',
            f'Assets/levels/{asset_graph["slug"]}/filelist.xml',
            f'Assets/levels/{asset_graph["slug"]}/level.pak',
            f'Assets/levels/{asset_graph["slug"]}/terraintexture.pak',
            f'Assets/levels/{asset_graph["slug"]}/layers/main.lyr',
            f'Assets/levels/{asset_graph["slug"]}/layers/terrain.lyr',
            f'Assets/levels/{asset_graph["slug"]}/leveldata/environment.xml',
            f'Assets/levels/{asset_graph["slug"]}/leveldata/timeofday.xml',
            f'Assets/levels/{asset_graph["slug"]}/leveldata/terraintexture.xml',
            f'Assets/levels/{asset_graph["slug"]}/leveldata/heightmap.dat',
            f'Assets/levels/{asset_graph["slug"]}/leveldata/vegetationmap.dat',
            f'Assets/levels/{asset_graph["slug"]}.level.cryasset',
        ],
    }
