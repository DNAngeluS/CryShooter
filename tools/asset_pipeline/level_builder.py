from __future__ import annotations

import struct
import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from .common import md5_file, write_text


def _make_cover_ctc(diffuse_rgba: list[int], height_rgba: list[int], sector_table_size: int) -> bytes:
    file_type = 100
    version = 9
    diff_pix = 64
    hmap_pix = 32
    diff_bytes = diff_pix * diff_pix * 4
    hmap_bytes = hmap_pix * hmap_pix * 4
    depth = 0
    size = sector_table_size
    while size > 1:
        size //= 2
        depth += 1
    tree_nodes = (4 ** (depth + 1) - 1) // 3
    common = b"CRY\x00" + struct.pack("<BBH", file_type, 0, version)
    tex_hdr = struct.pack("<HHf", 2, 0, 1.0)
    layer0 = struct.pack("<HHiI", diff_pix, 0, 2, diff_bytes)
    layer1 = struct.pack("<HHiI", hmap_pix, 0, 2, hmap_bytes)
    index_block = struct.pack("<H", tree_nodes) + b"".join(struct.pack("<h", i) for i in range(tree_nodes))
    diff_pixel = bytes(diffuse_rgba)
    hmap_pixel = bytes(height_rgba)
    one_tile = diff_pixel * (diff_pix**2) + hmap_pixel * (hmap_pix**2)
    return common + tex_hdr + layer0 + layer1 + index_block + one_tile * tree_nodes


def _empty_binary(size: int) -> bytes:
    return b"\x00" * size


def _level_file_xml(spec: dict) -> str:
    slug = spec["slug"]
    size = spec["world"]["heightmap_size"]
    center = size // 2
    return "\n".join(
        [
            '<Level WaterColor="16711680" SandboxVersion="5.6.5.30">',
            f' <View ViewerPos="{center - 3.3:.5f},{center - 3.8:.5f},35.03052" ViewerAngles="-0.51000333,0,0.068000369"/>',
            ' <Fog Fog="" Terrain="" EnvState="" VolFogShadows="" VolumetricCloud="" Ocean="" OceanAnimation="" DynTexSource=""/>',
            ' <Missions Current="Mission0">',
            '  <Mission Name="Mission0" Description="" PlayerEquipPack="" Script="" MissionTime="12:00">',
            '   <ObjectLayers LayerVersion="2" Current="Main" CurrentGUID="{}"/>'.format(uuid.uuid4()),
            "   <Objects />",
            f'   <Lighting SunRotation="{spec["lighting"]["sun_rotation"]}" SunHeight="{spec["lighting"]["sun_height"]}" Algorithm="3" Lighting="1" Shadows="1" ShadowIntensity="100" ILQuality="1" HemiSamplQuality="5" Longitude="90" DawnTime="355" DawnDuration="10" DuskTime="365" DuskDuration="10" SunVector="{spec["lighting"]["sun_vector"]}"/>',
            "   <Weapons>",
            "    <Used />",
            "    <Ammo />",
            "   </Weapons>",
            f'   <MiniMap CenterX="{center}" CenterY="{center}" ExtendsX="{center}" ExtendsY="{center}" TexWidth="1024" TexHeight="1024"/>',
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


def _levelinfo_xml(spec: dict) -> str:
    world = spec["world"]
    return "\n".join(
        [
            f'<LevelInfo SandboxVersion="5.6.5.30" Name="assets/levels/{escape(spec["slug"])}" HeightmapSize="200">',
            f' <TerrainInfo HeightmapSize="{world["heightmap_size"]}" UnitSize="{world["unit_size"]}" SectorSize="{world["sector_size"]}" SectorsTableSize="{world["heightmap_size"] // world["sector_size"]}" HeightmapZRatio="{world["heightmap_z_ratio"]}" OceanWaterLevel="{world["ocean_water_level"]}"/>',
            " <Missions>",
            '  <Mission Name="Mission0" Description=""/>',
            " </Missions>",
            "</LevelInfo>",
            "",
        ]
    )


def _leveldata_xml(spec: dict) -> str:
    world = spec["world"]
    return "\n".join(
        [
            '<LevelData SandboxVersion="5.6.5.30">',
            f' <LevelInfo CreationDate="03/29/26" Name="{escape(spec["slug"])}" HeightmapSize="200" HeightmapUnitSize="{world["unit_size"]}" HeightmapMaxHeight="{world["max_height"]}" WaterLevel="{world["ocean_water_level"]}" TerrainSectorSizeInMeters="{world["sector_size"]}"/>',
            ' <SurfaceTypes>',
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


def _timeofday_xml(spec: dict) -> str:
    return "\n".join(
        [
            f'<TimeOfDay Time="{spec["lighting"]["time_hour"]}" TimeStart="0" TimeEnd="24" TimeAnimSpeed="0">',
            " <Presets>",
            f'  <Preset Name="{spec["lighting"]["preset"]}" Default="1"/>',
            " </Presets>",
            "</TimeOfDay>",
            "",
        ]
    )


def _mission_xml(spec: dict) -> str:
    world = spec["world"]
    center = world["heightmap_size"] // 2
    return "\n".join(
        [
            '<Mission Name="Mission0" Description="" Time="12:00" PlayerEquipPack="" Script="" CGFCount="0">',
            " <Environment>",
            '  <Fog ViewDistance="8000" ViewDistanceLowSpec="1000" LDRGlobalDensMult="1.0"/>',
            '  <Terrain DetailLayersViewDistRatio="1.0" HeightMapAO="0" IntegrateObjects="0" AutoGenerateBaseTexture="0" SupportOfflineProceduralVegetation="0"/>',
            '  <EnvState ConsoleMergedMeshesPool="2750" ShowTerrainSurface="1" SunShadowsMinSpec="1" SunShadowsAdditionalCascadeMinSpec="0" SunShadowsClipPlaneRange="256.0f" SunShadowsClipPlaneRangeShift="0.0f" SunShadowsFromTerrain="0" UseLayersActivation="0"/>',
            '  <VolFogShadows Enable="0" EnableForClouds="0"/>',
            '  <VolumetricCloud HorizonHeight="-1000.0" MaxViewableDistance="100000.0" MaxRayMarchDistance="20000.0" ShadingLOD="0.7" ShadowTilingSize="16000" MaxGlobalCloudDensity="0.04" GlobalCloudNoiseVolumeTexture="" GlobalCloudNoiseScale="3,3,5" EdgeTurbulenceNoiseVolumeTexture="" EdgeTurbulenceNoiseScale="1,1,1" EdgeTurbulenceNoiseErode="1" EdgeTurbulenceNoiseAbsolute="1" CloudVolumeTexture="" TilingSize="64000,64000,4000" TilingOffset="0,0,0" RemapCloudDensityMin="0.0" RemapCloudDensityMax="1.0" AdditionalNoiseIntensity="0.2"/>',
            '  <Ocean Material="%ENGINE%/EngineAssets/Materials/Water/Ocean_default" CausticDepth="8.0" CausticIntensity="1.0" CausticsTilling="1.0"/>',
            '  <OceanAnimation WindDirection="1.0" WindSpeed="4.0" WavesAmount="1.5" WavesSize="0.4"/>',
            '  <DynTexSource Width="256" Height="256"/>',
            f'  <Lighting SunRotation="{spec["lighting"]["sun_rotation"]}" SunHeight="{spec["lighting"]["sun_height"]}" Algorithm="3" Lighting="1" Shadows="1" ShadowIntensity="100" ILQuality="1" HemiSamplQuality="5" Longitude="90" DawnTime="355" DawnDuration="10" DuskTime="365" DuskDuration="10" SunVector="{spec["lighting"]["sun_vector"]}"/>',
            " </Environment>",
            f' <TimeOfDay Time="{spec["lighting"]["time_hour"]}" TimeStart="0" TimeEnd="24" TimeAnimSpeed="0">',
            "  <Presets>",
            f'   <Preset Name="{spec["lighting"]["preset"]}" Default="1"/>',
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


def _terrain_texture_xml(spec: dict) -> str:
    terrain = spec["terrain"]
    rows = []
    for y in range(terrain["tile_count_y"]):
        for x in range(terrain["tile_count_x"]):
            rows.append(f'   <tile X="{x}" Y="{y}" Size="{terrain["tile_resolution"]}"/>')
    return "\n".join(
        [
            f'<TerrainTexture TileCountX="{terrain["tile_count_x"]}" TileCountY="{terrain["tile_count_y"]}" TileResolution="{terrain["tile_resolution"]}">',
            " <RGBLayer>",
            "  <Tiles>",
            *rows,
            "  </Tiles>",
            " </RGBLayer>",
            "</TerrainTexture>",
            "",
        ]
    )


def _layer_xml(name: str, layer_type: int, extra_files: list[str] | None = None) -> str:
    guid = uuid.uuid4()
    lines = [
        "<ObjectLayer>",
        f' <Layer Name="{name}" FullName="{name}" GUID="{guid}" Hidden="0" Frozen="0" Expanded="0" Type="{layer_type}" Exportable="1" ExportLayerPak="1" DefaultLoaded="0" HavePhysics="1" IsDefaultColor="1" Color="4671303" Timestamp="1777777777">',
    ]
    if extra_files:
        lines.append("  <Files>")
        for file_path in extra_files:
            lines.append(f'   <File path="{file_path}"/>')
        lines.append("  </Files>")
    else:
        lines.extend(["  <LayerObjects />"])
    lines.extend([" </Layer>", "</ObjectLayer>", ""])
    return "\n".join(lines)


def _cryasset_xml(spec: dict) -> str:
    slug = spec["slug"]
    guid = uuid.uuid4()
    return "\n".join(
        [
            f'<AssetMetadata version="0" type="Level" guid="{guid}" source="" timestamp="1777777777">',
            " <Files>",
            f'  <File path="{slug}/{slug}.level"/>',
            " </Files>",
            " <Dependencies>",
            '  <Path usageCount="1">%ENGINE%/EngineAssets/Shading/default.env</Path>',
            "  <Path>%editor%/crydesigner_timeofday.xml</Path>",
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


def build_level_job(stage_assets_root: Path, spec: dict) -> dict:
    slug = spec["slug"]
    level_root = stage_assets_root / "Assets" / "levels" / slug
    level_root.mkdir(parents=True, exist_ok=True)
    (level_root / "layers").mkdir(exist_ok=True)
    (level_root / "leveldata").mkdir(exist_ok=True)

    level_file = level_root / f"{slug}.level"
    write_text(level_file, _level_file_xml(spec))
    write_text(level_root / "leveldata" / "environment.xml", _environment_xml())
    write_text(level_root / "leveldata" / "timeofday.xml", _timeofday_xml(spec))
    write_text(level_root / "leveldata" / "terraintexture.xml", _terrain_texture_xml(spec))
    (level_root / "leveldata" / "gametokens.xml").write_text("<GameTokens />\n", encoding="utf-8")
    (level_root / "leveldata" / "objectives.xml").write_text("<Objectives />\n", encoding="utf-8")
    (level_root / "leveldata" / "vegetationmap.dat").write_bytes(_empty_binary(128))
    heightmap_size = spec["world"]["heightmap_size"]
    heightmap_bytes = _empty_binary(heightmap_size * heightmap_size * 2)
    (level_root / "leveldata" / "heightmap.dat").write_bytes(heightmap_bytes)
    write_text(level_root / "layers" / "main.lyr", _layer_xml("Main", 0))
    write_text(
        level_root / "layers" / "terrain.lyr",
        _layer_xml("Terrain", 2, ["LevelData/Heightmap.dat", "LevelData/TerrainTexture.xml", "TerrainTexture.pak"]),
    )

    sector_table_size = heightmap_size // spec["world"]["sector_size"]
    cover_ctc = _make_cover_ctc(spec["terrain"]["diffuse_rgba"], spec["terrain"]["height_rgba"], sector_table_size)
    terraintexture_pak = level_root / "terraintexture.pak"
    with zipfile.ZipFile(terraintexture_pak, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("terrain/cover.ctc", cover_ctc)

    level_pak = level_root / "level.pak"
    with zipfile.ZipFile(level_pak, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("areasmission0.bai", b"")
        archive.writestr("brushlist.txt", "")
        archive.writestr("covermission0.bai", b"")
        archive.writestr("dyntexsrclayeract.xml", "<DynTexSourceLayerAct />\n")
        archive.writestr("lensflarelist.xml", "<LensFlares />\n")
        archive.writestr("leveldata.xml", _leveldata_xml(spec))
        archive.writestr("leveldataaction.xml", "<LevelDataAction />\n")
        archive.writestr("levelinfo.xml", _levelinfo_xml(spec))
        archive.writestr("levelparticles.xml", "<ParticlesLibrary />\n")
        archive.writestr("levelprototypes.xml", "<EntityPrototypeLibrary />\n")
        archive.writestr("mission_mission0.xml", _mission_xml(spec))
        archive.writestr("mnmnavmission0.bai", b"")
        archive.writestr("moviedata.xml", "<MovieData />\n")
        archive.writestr("perlayerresourcelist.txt", "")
        archive.writestr("resourcelist.txt", "")
        archive.writestr("serialize.xml", "<Serialize />\n")
        archive.writestr("shaderslist.txt", "")
        archive.writestr("terrain/cover.ctc", cover_ctc)
        archive.writestr("terrain/indoor.dat", b"")
        archive.writestr("terrain/merged_meshes_sectors/mmrm_used_meshes.lst", "")
        archive.writestr("terrain/terrain.dat", heightmap_bytes)

    filelist = "\n".join(
        [
            f'<download name="{slug}" type="Map">',
            ' <index src="filelist.xml" dest="filelist.xml"/>',
            " <files>",
            f'  <file src="level.pak" dest="level.pak" size="{level_pak.stat().st_size}" md5="{md5_file(level_pak)}"/>',
            " </files>",
            "</download>",
            "",
        ]
    )
    write_text(level_root / "filelist.xml", filelist)
    write_text(stage_assets_root / "Assets" / "levels" / f"{slug}.level.cryasset", _cryasset_xml(spec))

    return {
        "published_assets_root": f"Assets/levels/{slug}",
        "level_root": level_root.as_posix(),
        "files": [
            f"Assets/levels/{slug}/{slug}.level",
            f"Assets/levels/{slug}/filelist.xml",
            f"Assets/levels/{slug}/level.pak",
            f"Assets/levels/{slug}/terraintexture.pak",
            f"Assets/levels/{slug}/layers/main.lyr",
            f"Assets/levels/{slug}/layers/terrain.lyr",
            f"Assets/levels/{slug}/leveldata/environment.xml",
            f"Assets/levels/{slug}/leveldata/timeofday.xml",
            f"Assets/levels/{slug}/leveldata/terraintexture.xml",
            f"Assets/levels/{slug}.level.cryasset",
        ],
    }

