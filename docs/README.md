# Documentation

Everything a person needs to work on this project, in reading order. For the quick start (install,
build, run) see the [project README](../README.md).

## Start here

| Document | Read it to… |
|---|---|
| [Architecture overview](architecture.md) | understand how the game plugin, the asset pipeline and the engine fit together |
| [Asset pipeline](asset_pipeline.md) | generate levels, characters and meshes with the bundle-graph pipeline |
| [Known issues](known-issues.md) | see which log warnings and errors are expected, fixed or still open |

## CRYENGINE 5.6 knowledge base

These guides record what we learned getting CRYENGINE 5.6 to render correctly on Linux. Each one starts with who needs it.

| Guide | Covers |
|---|---|
| [Terrain](terrain.md) | level file layout, heightmap settings, water, spawn points, editing `level.pak` |
| [Terrain textures](textures.md) | the `cover.ctc` binary format and how to generate it |
| [Level of detail](lod.md) | terrain LOD CVars, causes and fixes for z-fighting |
| [Lighting](lighting.md) | time-of-day presets, sky, sun, shadows, lighting CVars |
| [Character mesh & animation](character_mesh.md) | Mannequin setup, character controller, camera, attachments |
| [DDS normal-map format](dds_normal_map_format.md) | why `_ddn` textures must be BC5 and how the engine ones were fixed |

## "Something looks wrong" — find the right guide

| What you see | Most likely cause | Read |
|---|---|---|
| Whole screen black | missing time-of-day preset file | [Lighting](lighting.md#the-most-common-cause-of-a-black-screen) |
| Terrain is solid black | empty or invalid `terraintexture.pak` | [Terrain textures](textures.md) |
| Black patches spreading as you walk | `e_TerrainAutoGenerateBaseTexture` enabled on a generated level | [Terrain textures](textures.md#e_terrainautogeneratebasetexture) |
| Flickering at the shoreline or terrain seams | ocean co-planar with terrain, or coarse terrain LOD | [LOD](lod.md#why-z-fighting-happens) |
| You spawn underground | no spawn point in the level | [Terrain](terrain.md#spawn-points) |
| No arms or weapon on screen | first-person character failed to load | [Character mesh](character_mesh.md) · [Known issues](known-issues.md) |
| "Wrong format for normal map" in the log | `_ddn` texture not BC5 | [DDS normal maps](dds_normal_map_format.md) |
| Dozens of "Texture does not exist … rain" warnings | engine ships uncompiled weather textures | [Known issues](known-issues.md#missing-engine-textures) |

## Who maintains what

Pages in this folder are written for people and edited deliberately. Working notes, plans and
session status for AI agents live in `.agents/` and `.memory/`, not here — see
[`AGENTS.md`](../AGENTS.md) at the project root.
