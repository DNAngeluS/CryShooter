from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .character_builder import build_first_person_character_package
from .common import md5_file, project_root, read_json, relative_to_repo, write_json, write_text
from .mesh_converter import stage_mesh_asset
from .texture_builder import average_rgba, build_terraintexture_pak, emit_imagegen_request, generate_texture_pixels, write_png
from .catalogs import (
    load_level_template_catalog,
    load_material_template_catalog,
    load_procedural_mesh_catalog,
)


OVERRIDDEN_LEVEL_PAK_ENTRIES = {"leveldata.xml", "levelinfo.xml", "mission_mission0.xml"}


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


def _resolve_level_template(profile: str, heightmap_size: int, root: Path) -> dict[str, Any]:
    catalog = load_level_template_catalog(root)
    for template in catalog["templates"]:
        if template["profile"] == profile and template["heightmap_size"] == heightmap_size and template.get("available"):
            return template
    raise ValueError(f"No checked-in template for terrain profile={profile} size={heightmap_size}")


def _material_xml(spec: dict[str, Any], diffuse_file: str, template: dict[str, Any]) -> str:
    return "\n".join(
        [
            f'<Material MtlFlags="524288" Shader="{template["shader"]}" GenMask="80000000" StringGenMask="%SUBSURFACE_SCATTERING" SurfaceType="{spec["surface_type"]}" MatTemplate="" Diffuse="{template["diffuse"]}" Specular="{template["specular"]}" Emissive="0,0,0" Shininess="{template["shininess"]}" Opacity="{template["opacity"]}" LayerAct="1">',
            " <Textures>",
            f'  <Texture Map="Diffuse" File="{diffuse_file}"/>',
            " </Textures>",
            ' <PublicParams SSSIndex="0" IndirectColor="0.25,0.25,0.25"/>',
            "</Material>",
            "",
        ]
    )


def _material_cryasset_xml(name: str, relative_material_path: str) -> str:
    return "\n".join(
        [
            f'<AssetMetadata version="0" type="Material" guid="{uuid.uuid4()}">',
            " <Files>",
            f'  <File path="{relative_material_path}"/>',
            " </Files>",
            f" <Details><Detail name=\"name\">{escape(name)}</Detail></Details>",
            "</AssetMetadata>",
            "",
        ]
    )


def _mesh_cryasset_xml(filename: str, dependency_material: str) -> str:
    return "\n".join(
        [
            f'<AssetMetadata version="0" type="Mesh" guid="{uuid.uuid4()}">',
            " <Files>",
            f'  <File path="{filename}"/>',
            " </Files>",
            " <Details>",
            '  <Detail name="materialCount">1</Detail>',
            " </Details>",
            " <Dependencies>",
            f'  <Path usageCount="1">{dependency_material}</Path>',
            " </Dependencies>",
            "</AssetMetadata>",
            "",
        ]
    )


def _level_file_xml(level_slug: str, scene_spec: dict[str, Any], main_layer_guid: str, heightmap_size: int) -> str:
    center = heightmap_size / 2
    viewer_z = scene_spec["spawn"]["transform"]["position"][2]
    lighting = scene_spec["lighting"]
    return "\n".join(
        [
            '<Level WaterColor="16711680" SandboxVersion="5.6.5.30">',
            f' <View ViewerPos="{center:.3f},{center:.3f},{viewer_z:.3f}" ViewerAngles="0,-0,0"/>',
            ' <Fog Fog="" Terrain="" EnvState="" VolFogShadows="" VolumetricCloud="" SkyBox="" Ocean="" OceanAnimation="" DynTexSource=""/>',
            ' <Missions Current="Mission0">',
            '  <Mission Name="Mission0" Description="" PlayerEquipPack="" Script="" MissionTime="12:00">',
            f'   <ObjectLayers LayerVersion="2" Current="Main" CurrentGUID="{main_layer_guid}"/>',
            "   <Objects />",
            f'   <Lighting SunRotation="{lighting["sun_rotation"]}" SunHeight="{lighting["sun_height"]}" Algorithm="3" Lighting="1" Shadows="1" ShadowIntensity="100" ILQuality="1" HemiSamplQuality="5" Longitude="90" DawnTime="355" DawnDuration="10" DuskTime="365" DuskDuration="10" SunVector="{lighting["sun_vector"]}"/>',
            "   <Weapons>",
            "    <Used />",
            "    <Ammo />",
            "   </Weapons>",
            f'   <MiniMap CenterX="{heightmap_size // 2}" CenterY="{heightmap_size // 2}" ExtendsX="{heightmap_size // 2}" ExtendsY="{heightmap_size // 2}" TexWidth="1024" TexHeight="1024"/>',
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


def _levelinfo_xml(level_slug: str, world: dict[str, Any]) -> str:
    editor_size = _level_editor_size(world["heightmap_size"])
    return "\n".join(
        [
            f'<LevelInfo SandboxVersion="5.6.5.30" Name="assets/levels/{escape(level_slug)}" HeightmapSize="{editor_size}">',
            f' <TerrainInfo HeightmapSize="{world["heightmap_size"]}" UnitSize="{world["unit_size"]}" SectorSize="{world["sector_size"]}" SectorsTableSize="{world["heightmap_size"] // world["sector_size"]}" HeightmapZRatio="{world["heightmap_z_ratio"]}" OceanWaterLevel="{world["ocean_water_level"]}"/>',
            " <Missions>",
            '  <Mission Name="Mission0" Description=""/>',
            " </Missions>",
            "</LevelInfo>",
            "",
        ]
    )


def _leveldata_xml(level_slug: str, world: dict[str, Any], material_paths: list[str]) -> str:
    editor_size = _level_editor_size(world["heightmap_size"])
    lines = [
        '<LevelData SandboxVersion="5.6.5.30">',
        f' <LevelInfo CreationDate="03/29/26" Name="{escape(level_slug)}" HeightmapSize="{editor_size}" HeightmapUnitSize="{world["unit_size"]}" HeightmapMaxHeight="{world["max_height"]}" WaterLevel="{world["ocean_water_level"]}" TerrainSectorSizeInMeters="{world["sector_size"]}"/>',
        " <SurfaceTypes>",
    ]
    for index, path in enumerate(material_paths):
        lines.append(
            f'  <SurfaceType Name="{path}" SurfaceTypeID="{index}" DetailTexture="" DetailScaleX="1" DetailScaleY="1" DetailMaterial="{path}" ProjectAxis="2" Bumpmap="" ProjAxis="Z"/>'
        )
    lines.extend(
        [
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
    return "\n".join(lines)


def _timeofday_xml(scene_spec: dict[str, Any]) -> str:
    lighting = scene_spec["lighting"]
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


def _mission_xml(scene_spec: dict[str, Any], heightmap_size: int) -> str:
    lighting = scene_spec["lighting"]
    center = heightmap_size // 2
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


def _terrain_texture_xml(heightmap_size: int) -> str:
    tile_count = max(1, heightmap_size // 256)
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


def _brush_object_xml(placement: dict[str, Any], layer_guid: str, prefab_path: str, material_override: str | None) -> str:
    transform = placement["transform"]
    material_attribute = f' Material="{escape(material_override)}"' if material_override else ""
    return (
        f'   <Object Type="Brush" Layer="Main" LayerGUID="{layer_guid}" Id="{uuid.uuid4()}" '
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
    return "\n".join(
        [
            "<ObjectLayer>",
            f' <Layer Name="{name}" FullName="{name}" GUID="{guid}" Hidden="0" Frozen="0" Expanded="0" Type="{layer_type}" Exportable="1" ExportLayerPak="1" DefaultLoaded="0" HavePhysics="1" IsDefaultColor="1" Color="4671303" Timestamp="1777777777">',
            *body_lines,
            " </Layer>",
            "</ObjectLayer>",
            "",
        ]
    )


def _main_layer_xml(placements: list[dict[str, Any]], main_layer_guid: str) -> str:
    body_lines = ["  <LayerObjects>"]
    for placement in placements:
        body_lines.append(_brush_object_xml(placement, main_layer_guid, placement["asset_path"], placement.get("material_override")))
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


def _level_cryasset_xml(level_slug: str) -> str:
    return "\n".join(
        [
            f'<AssetMetadata version="0" type="Level" guid="{uuid.uuid4()}" source="" timestamp="1777777777">',
            " <Files>",
            f'  <File path="{level_slug}/{level_slug}.level"/>',
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


def _compile_texture_node(stage_root: Path, stage_assets_root: Path, bundle_slug: str, node: dict[str, Any], build_state: dict[str, Any]) -> dict[str, Any]:
    spec = node["spec"]
    texture_dir = stage_assets_root / "Assets" / "Textures" / "Generated" / bundle_slug
    texture_path = texture_dir / f'{spec["name"]}.png'
    mode = spec["mode"]
    if mode == "import":
        source = Path(spec["source_file"]).expanduser().resolve()
        texture_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, texture_path)
        average = spec.get("average_rgba", [128, 128, 128, 255])
        pixel_data = None
    else:
        if mode == "imagegen":
            emit_imagegen_request(stage_root / "imagegen_requests" / f'{node["id"]}.json', {"prompt": spec["prompt"], "bundle_slug": bundle_slug, "node_id": node["id"]})
        pixels, average = generate_texture_pixels(spec)
        write_png(texture_path, spec["width"], spec["height"], pixels)
        pixel_data = {"width": spec["width"], "height": spec["height"], "pixels": pixels}
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        "mode": mode,
        "asset_path": f"Textures/Generated/{bundle_slug}/{spec['name']}.png",
        "average_rgba": average,
    }
    if pixel_data:
        report["pixel_data"] = pixel_data
    build_state[node["id"]] = report
    return report


def _compile_material_node(stage_assets_root: Path, bundle_slug: str, node: dict[str, Any], build_state: dict[str, Any], root: Path) -> dict[str, Any]:
    template_name = node["spec"]["template"]
    template_catalog = load_material_template_catalog(root)
    template = next(item for item in template_catalog["templates"] if item["name"] == template_name)
    diffuse_node = build_state[node["inputs"]["diffuse_texture"]]
    material_dir = stage_assets_root / "Assets" / "Materials" / "Generated" / bundle_slug
    material_dir.mkdir(parents=True, exist_ok=True)
    material_name = node["spec"]["name"]
    material_path = material_dir / f"{material_name}.mtl"
    relative_diffuse = diffuse_node["asset_path"]
    write_text(material_path, _material_xml(node["spec"], relative_diffuse, template))
    write_text(material_path.with_suffix(".mtl.cryasset"), _material_cryasset_xml(material_name, f"{material_name}.mtl"))
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        "asset_path": f"Materials/Generated/{bundle_slug}/{material_name}.mtl",
        "diffuse_texture": relative_diffuse,
    }
    build_state[node["id"]] = report
    return report


def _compile_procedural_mesh_node(stage_assets_root: Path, bundle_slug: str, node: dict[str, Any], build_state: dict[str, Any], root: Path) -> dict[str, Any]:
    catalog = load_procedural_mesh_catalog(root)
    entry = next(item for item in catalog["archetypes"] if item["name"] == node["spec"]["archetype"])
    source_rel = entry["base_asset"]
    source = root / "Assets" / source_rel
    mesh_dir = stage_assets_root / "Assets" / "Objects" / "Generated" / bundle_slug
    mesh_dir.mkdir(parents=True, exist_ok=True)
    target_name = f'{node["spec"]["name"]}.cgf'
    target = mesh_dir / target_name
    shutil.copy2(source, target)
    dependency_material = entry["dependency_material"]
    material_override = None
    if "material" in node["inputs"]:
        material_override = build_state[node["inputs"]["material"]]["asset_path"]
        dependency_material = material_override
    write_text(target.with_suffix(".cgf.cryasset"), _mesh_cryasset_xml(target_name, dependency_material))
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        "asset_path": f"Objects/Generated/{bundle_slug}/{target_name}",
        "material_override": material_override,
        "archetype": node["spec"]["archetype"],
    }
    build_state[node["id"]] = report
    return report


def _compile_mesh_import_node(stage_root: Path, stage_assets_root: Path, node: dict[str, Any], build_state: dict[str, Any], root: Path) -> dict[str, Any]:
    spec = node["spec"]
    result = stage_mesh_asset(
        stage_root=stage_root,
        stage_assets_root=stage_assets_root,
        input_path=Path(spec["source_file"]).expanduser().resolve(),
        target=spec["target_path"],
        kind=spec["mesh_kind"],
        repo_root=root,
    )
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        **result,
    }
    build_state[node["id"]] = report
    return report


def _compile_terrain_node(stage_root: Path, stage_assets_root: Path, bundle_slug: str, node: dict[str, Any], build_state: dict[str, Any], root: Path) -> dict[str, Any]:
    spec = node["spec"]
    template = _resolve_level_template(spec["template_profile"], spec["heightmap_size"], root)
    template_level_root = root / template["source_level_dir"]
    terrain_stage_root = stage_root / "compiled_nodes" / node["id"]
    terrain_stage_root.mkdir(parents=True, exist_ok=True)
    heightmap_target = terrain_stage_root / "heightmap.dat"
    vegetation_target = terrain_stage_root / "vegetationmap.dat"
    shutil.copy2(template_level_root / "leveldata" / "heightmap.dat", heightmap_target)
    shutil.copy2(template_level_root / "leveldata" / "vegetationmap.dat", vegetation_target)
    first_material = build_state[node["inputs"]["paint_materials"][0]]
    diffuse_node = next(value for value in build_state.values() if value.get("asset_path") == first_material["diffuse_texture"])
    pixel_data = diffuse_node.get("pixel_data")
    if pixel_data:
        terraintexture_report = build_terraintexture_pak(
            terrain_stage_root / "terraintexture.pak",
            pixel_data["pixels"],
            pixel_data["width"],
            pixel_data["height"],
            spec["heightmap_size"] // 32,
        )
    else:
        pixels, _ = generate_texture_pixels({"mode": "solid_color", "width": 64, "height": 64, "rgba": diffuse_node["average_rgba"]})
        terraintexture_report = build_terraintexture_pak(terrain_stage_root / "terraintexture.pak", pixels, 64, 64, spec["heightmap_size"] // 32)
    terrain_manifest = {
        "template_id": template["template_id"],
        "paint_zones": spec["paint_zones"],
        "foliage_zones": spec["foliage_zones"],
        "paint_material_assets": [build_state[item]["asset_path"] for item in node["inputs"]["paint_materials"]],
        "foliage_mesh_assets": [build_state[item]["asset_path"] for item in node["inputs"].get("foliage_meshes", [])],
    }
    write_json(terrain_stage_root / "terrain_manifest.json", terrain_manifest)
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        "template_id": template["template_id"],
        "heightmap_size": spec["heightmap_size"],
        "heightmap_path": relative_to_repo(heightmap_target, base=root),
        "vegetationmap_path": relative_to_repo(vegetation_target, base=root),
        "terraintexture_pak_path": relative_to_repo(Path(terraintexture_report["path"]), base=root),
        "paint_material_assets": terrain_manifest["paint_material_assets"],
        "manifest_path": relative_to_repo(terrain_stage_root / "terrain_manifest.json", base=root),
        "template_level_dir": template["source_level_dir"],
        "world": {
            "heightmap_size": spec["heightmap_size"],
            "unit_size": 1,
            "sector_size": 32,
            "heightmap_z_ratio": 0.015625,
            "max_height": 1024,
            "ocean_water_level": -100,
        },
    }
    build_state[node["id"]] = report
    return report


def _compile_object_placement_set(node: dict[str, Any], build_state: dict[str, Any]) -> dict[str, Any]:
    placements = []
    for placement in node["spec"]["placements"]:
        mesh_report = build_state[placement["target_node"]]
        material_override = None
        if placement.get("material_node"):
            material_override = build_state[placement["material_node"]]["asset_path"]
        placements.append(
            {
                "name": placement["name"],
                "asset_path": mesh_report["asset_path"],
                "material_override": material_override or mesh_report.get("material_override"),
                "transform": placement["transform"],
            }
        )
    report = {"node_id": node["id"], "type": node["type"], "status": "built", "placements": placements}
    build_state[node["id"]] = report
    return report


def _compile_scene_level(stage_root: Path, stage_assets_root: Path, bundle_slug: str, node: dict[str, Any], build_state: dict[str, Any], root: Path) -> dict[str, Any]:
    terrain_report = build_state[node["inputs"]["terrain"]]
    scene_spec = node["spec"]
    level_slug = scene_spec["level_slug"]
    world = terrain_report["world"]
    template_level_root = root / terrain_report["template_level_dir"]
    level_root = stage_assets_root / "Assets" / "levels" / level_slug
    (level_root / "layers").mkdir(parents=True, exist_ok=True)
    (level_root / "leveldata").mkdir(exist_ok=True)
    shutil.copy2(root / terrain_report["heightmap_path"], level_root / "leveldata" / "heightmap.dat")
    shutil.copy2(root / terrain_report["vegetationmap_path"], level_root / "leveldata" / "vegetationmap.dat")
    shutil.copy2(root / terrain_report["terraintexture_pak_path"], level_root / "terraintexture.pak")
    write_json(level_root / "leveldata" / "terrain_manifest.json", read_json(root / terrain_report["manifest_path"]))

    placement_reports = [build_state[item]["placements"] for item in node["inputs"]["placement_sets"]]
    placements = [placement for group in placement_reports for placement in group]
    main_layer_guid = str(uuid.uuid4())
    terrain_layer_guid = str(uuid.uuid4())
    write_text(level_root / f"{level_slug}.level", _level_file_xml(level_slug, scene_spec, main_layer_guid, world["heightmap_size"]))
    write_text(level_root / "leveldata" / "environment.xml", "<Environment />\n")
    write_text(level_root / "leveldata" / "timeofday.xml", _timeofday_xml(scene_spec))
    write_text(level_root / "leveldata" / "terraintexture.xml", _terrain_texture_xml(world["heightmap_size"]))
    write_text(level_root / "leveldata" / "gametokens.xml", "<GameTokens />\n")
    write_text(level_root / "leveldata" / "objectives.xml", "<Objectives />\n")
    write_text(level_root / "layers" / "main.lyr", _main_layer_xml(placements, main_layer_guid))
    write_text(level_root / "layers" / "terrain.lyr", _terrain_layer_xml(terrain_layer_guid))

    template_level_pak = template_level_root / "level.pak"
    level_pak = level_root / "level.pak"
    with zipfile.ZipFile(template_level_pak) as source_archive, zipfile.ZipFile(level_pak, "w", zipfile.ZIP_DEFLATED) as target_archive:
        for name in sorted(source_archive.namelist()):
            if name in OVERRIDDEN_LEVEL_PAK_ENTRIES:
                continue
            target_archive.writestr(name, source_archive.read(name))
        target_archive.writestr("leveldata.xml", _leveldata_xml(level_slug, world, terrain_report["paint_material_assets"]))
        target_archive.writestr("levelinfo.xml", _levelinfo_xml(level_slug, world))
        target_archive.writestr("mission_mission0.xml", _mission_xml(scene_spec, world["heightmap_size"]))

    filelist = "\n".join(
        [
            f'<download name="{level_slug}" type="Map">',
            ' <index src="filelist.xml" dest="filelist.xml"/>',
            " <files>",
            f'  <file src="level.pak" dest="level.pak" size="{level_pak.stat().st_size}" md5="{md5_file(level_pak)}"/>',
            " </files>",
            "</download>",
            "",
        ]
    )
    write_text(level_root / "filelist.xml", filelist)
    write_text(stage_assets_root / "Assets" / "levels" / f"{level_slug}.level.cryasset", _level_cryasset_xml(level_slug))
    report = {
        "node_id": node["id"],
        "type": node["type"],
        "status": "built",
        "asset_path": f"levels/{level_slug}/{level_slug}.level",
        "level_slug": level_slug,
        "placements_compiled": len(placements),
    }
    build_state[node["id"]] = report
    return report


def build_asset_bundle(stage_root: Path, asset_graph: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    repo_root = root or project_root()
    stage_assets_root = stage_root / "staged_assets"
    build_state: dict[str, Any] = {}
    node_reports: list[dict[str, Any]] = []
    for node in asset_graph["dependency_order"]:
        if node["type"] == "texture_source":
            report = _compile_texture_node(stage_root, stage_assets_root, asset_graph["bundle_slug"], node, build_state)
        elif node["type"] == "material_surface":
            report = _compile_material_node(stage_assets_root, asset_graph["bundle_slug"], node, build_state, repo_root)
        elif node["type"] == "mesh_procedural":
            report = _compile_procedural_mesh_node(stage_assets_root, asset_graph["bundle_slug"], node, build_state, repo_root)
        elif node["type"] == "mesh_import":
            report = _compile_mesh_import_node(stage_root, stage_assets_root, node, build_state, repo_root)
        elif node["type"] == "terrain_archetype":
            report = _compile_terrain_node(stage_root, stage_assets_root, asset_graph["bundle_slug"], node, build_state, repo_root)
        elif node["type"] == "object_placement_set":
            report = _compile_object_placement_set(node, build_state)
        elif node["type"] == "scene_level":
            report = _compile_scene_level(stage_root, stage_assets_root, asset_graph["bundle_slug"], node, build_state, repo_root)
        elif node["type"] == "character_fp_package":
            report = build_first_person_character_package(stage_assets_root, asset_graph["bundle_slug"], node["id"], node["spec"], build_state[node["inputs"]["source_mesh"]])
            build_state[node["id"]] = report
        else:
            raise ValueError(f"Unsupported bundle node type: {node['type']}")
        node_reports.append({key: value for key, value in report.items() if key != "pixel_data"})

    root_report = build_state[asset_graph["root_scene"]]
    files = [relative_to_repo(path, base=repo_root) for path in (stage_assets_root / "Assets").rglob("*") if path.is_file()]
    manifest = {
        "asset_kind": asset_graph["asset_kind"],
        "bundle_kind": asset_graph["bundle_kind"],
        "bundle_slug": asset_graph["bundle_slug"],
        "root_scene": asset_graph["root_scene"],
        "root_report": {key: value for key, value in root_report.items() if key != "pixel_data"},
        "node_reports": node_reports,
        "files": sorted(files),
    }
    write_json(stage_root / "node_build_reports.json", manifest)
    return manifest
