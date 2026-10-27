# Architecture overview

This project has two halves that meet only through files on disk: a C++ **game plugin** that runs
inside CRYENGINE, and a Python **asset pipeline** that produces the levels and character packages
the plugin plays.

```
 Python asset pipeline (tools/)                         C++ game plugin (Code/)
 asset_graph.json ──build/validate──▶ staged job ──publish──▶ Assets/levels/<name>/ ──▶ CRYENGINE
 (written by an LLM)                                                                     │
                                                libGamePlugin.so ◀── GameLauncher loads it
```

## The game plugin (`Code/`)

Built as `libGamePlugin.so` and copied into the engine's `bin/linux_x64_gcc/` after every build,
because the Linux launcher resolves plugins relative to its own directory.

| Piece | What it does |
|---|---|
| `GamePlugin` | registers the plugin, auto-loads the startup level when running outside the editor, applies water and LOD settings after each level loads, adds a `goto` console command |
| `Player` component | first-person camera, movement and jumping, mouse look, shooting, debug mode (`K`) with screenshots (`P`), quit on `Esc` |
| `SpawnPoint` component | marks where the player starts; if a level has none, the player spawns above the terrain centre |
| `Bullet` component | projectile physics |

See [Terrain](terrain.md), [Level of detail](lod.md) and [Character mesh](character_mesh.md) for the engine details behind these choices.

## The asset pipeline (`tools/`)

An LLM writes a strict `asset_graph.json` describing a level (terrain, textures, materials, meshes,
placements) or a first-person character. Python never interprets prose: it validates the graph,
compiles each node in dependency order into a staged package under `user/asset_pipeline/jobs/`,
validates the result, and — only on an explicit `publish` — copies it into `Assets/`.

Terrain can come from verified templates or be generated procedurally (forest, desert, tundra, swamp,
savanna, volcanic), with interior and structured (castle, arena, …) generators for other layouts.
The full workflow, node types and constraints are in the [Asset pipeline guide](asset_pipeline.md).

## Build and tooling

CMake + Ninja with three supported compilers (GCC 9 by default, GCC 14, Clang). The engine location is
supplied through the `CRYENGINE_DIR` environment variable — see the [project README](../README.md).
An optional helper, `tools/plasmid-dev/plasmid_dev/shader_server.py`, compiles Vulkan shaders through Wine + DXC when
the engine's own compiler is unavailable on Linux.

## What is not covered yet

- No automated tests for the C++ plugin; the Python pipeline has a pytest suite in `tests/`.
- Generated levels have not all been smoke-tested inside the engine — see [Known issues](known-issues.md).
- Architecture decisions are not yet recorded as ADRs.
