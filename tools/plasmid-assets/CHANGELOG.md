# Changelog

## 0.16.0 - 2026-11-01 - occlusionTexture as an occlusion map (needs the sandbox shader extension)

- `occlusionTexture` is now written the way the other engines use it: the R channel scales the INDIRECT light only (glTF spec, Unreal, Unity, Godot), `strength` blends 1 -> r. The importer bakes `1 + strength x (r - 1)` into a single-channel BC4 map (`<name>_img<N>_occ[_s<strength>].dds`, linear, one file per strength), writes it as `<Texture Map="Custom">` and adds `%OCCLUSION_MAP` to the material's `StringGenMask`. Default on; `--no-occlusion-map` ignores the texture (with the old warning); a `texCoord` other than 0 is ignored with a warning.
- It needs the sandbox's engine shader extension (`engine-ext/` in the sandbox project: the Illum `%OCCLUSION_MAP` flag, the Custom slot read in the Z pass, the value carried in the fractional bits of the G-buffer's lighting-model channel and applied to the probe/GI light only). A stock engine ignores the unknown flag and the unused Custom texture: the model renders as before, without occlusion.
- `--bake-ao` stays as the fallback and wins over the map: it multiplies the occlusion into the baked diffuse (works on a stock engine and in the forward pass, but also darkens direct light). The two are never applied together.
- Fix: a standalone BC4 DDS (`write_dds(..., "bc4")`) carried the DX10 fourCC without the DX10 extension header, so the engine rejected it ("Unknown DDS pixel format"); it now writes dxgiFormat BC4_UNORM. The `_ddna` attached BC4 was not affected.
- Fix: the temporary PNG of a texture conversion is named with the process id, so two imports running at the same time into one folder no longer collide (the Lantern failure of 2026-10-31).
- Engine proof (plasmid-mcp 0.2.15 `examples/occlusion_proof.py`, six quads in one frame): direct light only, every quad matches the control (100-104); ambient only, white and strength 0 match the control (158-160), black at strength 1 falls to 23, grey 0.5 and black at strength 0.5 sit in between (118, 119); the stock shaders with the same assets show no difference in either condition (negative control).
- Tests: 201 (the occlusion tests replace the 0.15.0 "ignored by default" one).

## 0.15.0 - 2026-10-31 - doubleSided, normalTexture.scale, opt-in occlusion bake, shared-image fix

- `doubleSided`: a glTF material with `doubleSided: true` is written with `MtlFlags="2"` (`MTL_FLAG_2SIDED`, `IMaterial.h:49`; read per material node, `MatMan.cpp:427`, so each sub-material carries its own flag). The engine then draws both faces and the shader flips the normal of a back face (`CommonZPass.cfi:235`). Single sided stays the default, as in glTF.
- `normalTexture.scale`: applied as the glTF formula, n = normalize((rgb x 2 - 1) x (scale, scale, 1)), to the pixels before the BC5_SNORM encode, in the plain `_ddn` path and in the bake's `_ddna`. A scale of 1 (or none) is byte-identical to before; another scale writes `<name>_img<N>_s<scale>_ddn.dds` and is part of the cache key.
- `occlusionTexture`: the Illum shader has no occlusion map (`EFTT_*` has no slot), so by default the texture is ignored with a warning. `--bake-ao` multiplies it (red channel, 1 + strength x (o - 1)) into the baked diffuse map, which also darkens direct light; it needs the bake path, and a material with an occlusionTexture and no metallicRoughnessTexture is now baked from its factors. `MaterialOptions.ao`.
- Fix: two materials that share one image now both get the texture; before, only the first material using an image had an entry and the second was written with the white texture.
- Engine proof (plasmid-mcp 0.2.13 `examples/importer_items_proof.py`, one frame): scale 0 lights like the flat control (100 vs 100), brightness rises with the scale (flat 100, 0.5 206, 1 220, 2 226); a single-sided quad seen from behind is culled (122 against background 130), the doubleSided one is visible and lit like the front view (222 vs 227, so the normal is flipped).
- Tests: 196 (new `test_importer_items.py`).
- Still not done: `KHR_texture_transform` and non-zero texCoord on baked maps (fall back), JPEG sources (fall back), a detail map, IndirectColor, SSS.

## 0.14.0 - 2026-10-31 - metallicRoughnessTexture is baked per texel

- BEHAVIOUR CHANGE: `gltf2cgf` and `gltf2chr` bake a material's `metallicRoughnessTexture` into the maps the Illum shader reads (`plasmid_assets/bake.py`), in linear light: a diffuse map `<name>_m<N>_d.dds` = base x baseColorFactor x (1 - m) (BC1, BC3 only for BLEND/MASK with alpha, sRGB), a reflectance map `<name>_m<N>_spec.dds` = 0.04 + (base x factor - 0.04) x m (BC1, sRGB), and the gloss 1 - r as the attached alpha of `<name>_m<N>_ddna.dds` (the normal map, or a neutral one at the bake size when the material has none); m = metallicFactor x B, r = roughnessFactor x G (the red channel is ignored). The `.mtl` then carries `Diffuse="1,1,1" Specular="1,1,1" Shininess="255"`, a `Specular` texture row and `StringGenMask="%NORMAL_MAP%SPECULAR_MAP"` (`Illum.cfx:489`). Materials without a metallicRoughnessTexture are unchanged. Textures of different sizes are resampled bilinearly to the larger one; the gloss is resampled to the normal map's size.
- `--no-bake` keeps the 0.13.0 output (the factors scaled by the texture's mean, with a warning). A material whose maps cannot be baked (a non-PNG image, a texCoord other than 0, KHR_texture_transform) falls back to that path with a warning naming the reason.
- The content-hash cache covers the bake: the key hashes every source image, the factors and a bake version, and the pixels are computed only on a miss; the cache now accepts files with an attached alpha.
- Engine proof (plasmid-mcp 0.2.12 `examples/bake_proof.py`, one frame): a sphere with a metal/dielectric split matches the scalar import of each half (upper 60 vs 61, lower 143 vs 142), a roughness split matches too (42 vs 42, 116 vs 116), the `--no-bake` import matches neither half (186 and 93 against 61 and 142). Real model: the Sketchfab Colt M1911 (base, normal and metallic-roughness textures) shows a brown non-metal grip next to dark steel where the mean approximation is one grey (`examples/reimport_compare.py`).
- Tests: 184 (new `test_bake.py`: sRGB round trip, the maths, the three files, neutral normal, cache hit, fallbacks, `.mtl` text, `--no-bake`).
- Still not done: `occlusionTexture`, `doubleSided`, `normalTexture.scale`, the mesh `Material` override.

## 0.13.0 - 2026-10-31 - `_ddna`: per-texel gloss in the normal map's attached alpha (writer; not yet baked from glTF)

- `png2dds --format bc5s --gloss <png>` (and `dds.write_dds(..., gloss=bytes)`) writes the engine-built `_ddna` layout, copied from `SampleCharacter/mcg_ddna.dds`: the DX10 `BC5_SNORM` normal map with `EIF_AttachedAlpha` (0x400) in `dwReserved1`, then `CExt` `AttC` <u32 size> + a full DX10 `BC4_UNORM` DDS (same size and mip count, `CRYF` stage, its own empty `CExt`/`CEnd`) + `CEnd`. The file must be named `*_ddna.dds` (the engine's suffix table); the normal-map naming rule now accepts `_ddna.dds`. `--gloss` cannot be combined with `--cache-dir`.
- Engine proof (plasmid-mcp 0.2.11 `examples/gloss_proof.py`, probe reflection, negative control): a sphere whose attached gloss is 255 on the left half of the visible surface and 0 on the right shows the mirror look on the left (same as the control sphere, difference 1) and a clearly different, diffuse look on the right (difference 122 in the upper band); the control sphere (`_ddn`, no attached alpha) is uniformly glossy. The shader reads it as `Shininess/255 x alpha` (smoothness 1 = glossy, no inversion). It is NOT wired into `gltf2cgf` yet: baking `metallicRoughnessTexture` into gloss (1 - roughness) and into a `_spec` map is the next step.
- Tests: 172 (new `AttachedGlossTest`: layout against the engine-built file, decode back, argument rules).

## 0.12.0 - 2026-10-31 - Normal maps are signed: DX10 BC5_SNORM

- BEHAVIOUR CHANGE: `gltf2cgf` and `gltf2chr` write the normal map (`*_ddn.dds`) as a DX10 `BC5_SNORM` file instead of unsigned `ATI2`. The engine samples a normal map as already signed (`common.cfi` `GetXYNormalMap` returns the raw `.yx`, no `*2-1`; `z = sqrt(1 - x^2 - y^2)`), and so does the engine-built `mcg_ddna.dds` (dxgi 84). An unsigned neutral map (128, 128) was read as (0.5, 0.5): a constant tilt of 0.5 along the tangent and the bitangent, so a camera-facing quad lit from one side only (the side of its tangent). Found by the Crytek domain session (`Crytek/.agents/handoffs/to-sandboxllm-2026-10-31-normalmap-and-shutdown-answer.md`): rewriting the proof's maps as signed made every pair of `normalmap_proof.py` pass and every ordering flip with the lamp. **Re-import every model that has a normal map** (the old files carry the bias; OF-23 is very likely the same cause).
- New `png2dds --format bc5s` (DX10 header, dxgiFormat 84, `CRYF` block and persistent mips kept; naming rule `*_ddn.dds` and the no-sRGB rule as for `bc5`; the byte value b maps to round((2b - 255)/255 x 127), 128 = signed 0). `bc5` (unsigned ATI2) stays for byte parity with the FPS writer; the cache accepts DX10 entries and the version bump invalidates old ones.
- Parity: two lines of `tests/parity.sha256` changed (`imp_gltf/two_img1_ddn.dds` and `imp_gltf.json`, the manifest names the format); the rest, including the `bc5` file, is byte-identical.
- Tests: 169 (new `Bc5SnormTest`, cache hit of a DX10 file, `bc5s` decode bound).
- Still not done: the per-texel gloss bake (`_ddna` must be written in this SNORM layout with `EIF_AttachedAlpha`, see `mcg_ddna.dds`), per-texel `metallicRoughnessTexture`, `occlusionTexture`, `doubleSided`.

## 0.11.0 - 2026-10-31 - emissiveTexture becomes the Emittance map

- `gltf2cgf` and `gltf2chr` convert a material's `emissiveTexture` to an sRGB BC1 `<name>_img<N>_em.dds` and write `<Texture Map="Emittance" File=.../>` next to the `Emittance="r,g,b,intensity"` attribute (factor and intensity as before). The Illum shader has no GenMask for it (`illum.cfx` binds `TM_Emittance` always): it multiplies the attribute by the map's rgb x alpha, so the file has no alpha channel (BC1). An `emissiveTexture` without an `emissiveFactor` emits nothing in glTF and warns. `--no-pbr` skips the texture (the 0.9.1 output).
- Engine proof (plasmid-mcp 0.2.9 `examples/emissive_texture_proof.py`): a sphere whose emissive texture is green on the top half and black below glows only on top (G 228 vs bottom mean 52), the same material without the texture glows uniformly (192 and 192); V orientation confirmed.
- Tests: 164 (new `EmissiveTextureTest`: `_em.dds` name, sRGB flag, no GenMask, `emissive=False`).
- Still not done: per-texel `metallicRoughnessTexture` bake, `occlusionTexture`, `doubleSided`, normal-map conventions (see the sandbox finding `2026-10-31-normalmap-direction-open.md`).

## 0.10.0 - 2026-10-30 - Materials: specular, shininess, emissive, alpha modes, --opaque

- BEHAVIOUR CHANGE: `gltf2cgf` and `gltf2chr` now write the glTF PBR parameters into the `.mtl`, so imported models react to light. Until now a material carried only `Diffuse`, `Opacity` and textures; the engine's Illum shader defaults `Specular` and `Shininess` to 0, which makes such a material pure Lambert: no highlight from any light (a point light's `specular` multiplier had nothing to scale), no reflections of the environment probe. Engine-proven 2026-10-30 (sandbox `docs/findings/2026-10-30-materials-lighting.md`, plasmid-mcp `examples/material_proof.py`).
- Mapping (`plasmid_assets/materials.py`, specular-colour workflow): `Diffuse` = baseColor x (1 - metallic); `Specular` = lerp(0.04, baseColor, metallic), linear; `Shininess` = (1 - roughness) x 255; `Emittance` = emissiveFactor with intensity 10 (the shader multiplies rgb by intensity/10; `KHR_materials_emissive_strength` multiplies it). A material without a `pbrMetallicRoughness` block stays matte. A `metallicRoughnessTexture` is not baked per texel: its mean over a 64x64 grid scales the factors, and the manifest warns.
- Alpha modes: OPAQUE ignores the base colour alpha (it used to become `Opacity`), BLEND keeps `Opacity`, MASK writes `AlphaTest` (the cutoff, default 0.5).
- New flags on both converters: `--opaque all|Name,Name` forces BLEND materials opaque (a blended material is drawn in the engine's forward pass: no ambient light, visible only where a direct light reaches it; this is the option the light-room session asked for), `--no-pbr` writes the 0.9.1 matte output, `--emissive-intensity N` (default 10).
- Not done (each needs its own engine proof): per-texel metalness/roughness baking into `_spec` and gloss maps, `emissiveTexture` to `%EMITTANCE_MAP` (ignored with a warning today), `occlusionTexture`, `doubleSided`, the normal-map Y convention and tangents.
- Tests: 161 (new `test_materials.py`: mapping, alpha modes, `--opaque`, emissive, texture mean, `.mtl` text).

## 0.9.1 - 2026-10-29 - Skins under a uniformly scaled ancestor (FBX centimetre wrapper)

- Fixed: `gltf2chr` refused real FBX/Sketchfab exports with `joint '_rootJoint' has scale in its bind pose`. Those files hang the skeleton under a node with a uniform scale (here `Rig`, rotation -90 deg about X, scale 100), so every joint's WORLD bind matrix carries that scale. When all joints share one uniform scale S (within 1e-3 relative; S may be 100, 0.01, ...) and are otherwise rigid, S is now folded into the output instead: bones stay orthonormal (rotation R, translation = world position, which already holds S), the mesh is skinned through `joint_world * inverseBind` as glTF defines, and the local translation keys of every joint are multiplied by S (rotation keys unchanged), so the CAF positions (cm) agree with the bind pose. A warning states the folded scale.
- Still refused with the same message style: non-uniform scale, or a scale that differs between joints.
- Real model checked (Sketchfab cat, 36 joints, one animation, `Rig` scale 100): converts; bone frame 0 of the animation reproduces the bind pose to 2 mm. Note the glTF data of that file, taken literally, make the cat about 580 units long (raw mesh 5.8 units, `joint_world * inverseBind` is a scale of 100 for every weighted joint), so the output is 100x a house cat; use `--scale 0.001` for about 0.58 m. The importer does not guess units.
- Tests: 147 passed, 1 skipped on the merged tree (0.9.0 alone: 144 passed; +3 here): wrapped rig with scale 100 and 0.01 (with a -90 deg rotation) equals the plain rig in bone positions, skin positions, weights and animation keys; non-uniform and per-joint scale still raise `SkinError`.

## 0.9.0 - 2026-10-28 - Environment-probe cube maps: probe-cubemap

- New command `probe-cubemap <out_dir> [--name N] [--sky r,g,b] [--horizon r,g,b] [--ground r,g,b] [--size 256]` and module `plasmid_assets.cubemap`: writes `<name>_cm.dds` (specular, 256 square, 7 mips down to 4) and `<name>_cm_diff.dds` (cosine-convolved diffuse, 32 square) as BC6H unsigned-float cube maps without the resource compiler. The engine's tiled shading keeps probes in a BC6UH atlas and refuses any other format (uncompressed half floats were tried and rejected: "Unsupported texture format ... it has to be equal to the tile-atlas (F:BC6UH)").
- The encoder writes BC6H mode 11 (one region, 10-bit endpoints, 4-bit indices); `decode_bc6h_mode11` is the matching decoder the tests use.
- Engine-verified from frames (plasmid-mcp 0.3.0): the cube faces are sampled in world axes (the side facing +X shows face 0, +Y face 2) and +Z (face 4) is the sky, so a blue sky face and a red ground face give a blue glow on up-facing surfaces. Without any probe, surfaces the sun does not reach are pure black (sandbox TASK-sandboxllm-mcp-24).
- The specular mips are the same gradient sampled at each size (no roughness blur): enough for a smooth sky; not a baked scene capture.

## 0.8.2 - 2026-10-28 - Real models; 0.8.1's tangent change reverted

- REVERTED: 0.8.1 negated the tangent frame handedness of skins. That was a mistake: it only compensated for a test rig whose triangles were wound against its normals (the engine then lights the inside faces of the far wall). The tangent frame of a skin is the static one again (`cgf.py`), a test pins it. If you vendored 0.8.1, re-vendor 0.8.2; output of 0.8.1 renders inverted on correctly wound models.
- Added: a warning when most triangles are wound against their vertex normals ("the engine will light the inside faces"), the symptom being a black or inverted skin.
- Fixed with real models (Khronos RiggedFigure, RiggedSimple, Fox, all CC-BY 4.0, downloaded for the test, not stored): skinning to the bind pose now follows glTF (`joint_world * inverseBind * v`, in the scene's world space): a model whose skeleton and mesh hang under a rotated node (RiggedFigure's `Z_UP`) was lying on its back; joints defined by `matrix` (RiggedSimple) are decomposed instead of refused; a primitive without NORMAL (Fox) gets smooth normals. Still refused: JPEG textures (CesiumMan), the importer reads PNG only.
- A skeleton whose root joint is rotated by such a parent now gets the synthetic `root` bone (the engine wants the root near identity).
- Engine-verified from frames: a real skinned model drawn, lit, animated (plasmid-mcp 0.2.3).

## 0.8.1 - 2026-10-28 - Skinned meshes: tangent frame handedness

- Fix: a skin written by `gltf2chr` rendered black in the engine (lit by no light, sun included) because the engine derives a skin's normal from the tangent frame with the opposite sign of a static mesh, so every normal pointed inward. The TANGENTS stream of `.skin` and `.chr` now carries the negated handedness. Found by looking at the engine's normals debug view (`r_DebugGBuffer 1`): after the change the four faces of the test column read outward as expected (-Y (125,0,128), +X (255,123,128), +Y (130,255,127), -X (0,132,127)), and a real skinned character rendered lit beside it in the same scene. Static `.cgf` output is unchanged. A test pins the sign.
- Engine-proven visually (plasmid-mcp 0.2.2 `examples/chr_proof.py`): the converted character is drawn, lit, and animated by the engine.

## 0.8.0 - 2026-10-28 - Skinned characters: gltf2chr

- New command `gltf2chr <in.gltf|in.glb> <out_dir> --game-dir DIR [--name NAME] [--scale S] [--jobs N] [--cache-dir DIR]` and module `plasmid_assets.skin`: a glTF skin becomes the compiled character files the engine loads without RC: `<name>.chr` (skeleton and a one-triangle proxy mesh), `<name>.skin` (mesh, bone mapping, bone boxes), `<name>.cdf`, `<name>.chrparams` (with `#filepath`, because a bare animation path is looked up under `animations/`), `<name>_<animation>.caf` per glTF animation (uncompressed controllers, 30 Hz, positions in cm), `<name>.mtl` and the textures. Prints a JSON manifest.
- Engine-proven (5.6.7, log-asserted in plasmid-mcp 0.2.1 `examples/chr_proof.py`): bone names, parents and bind positions, skin vertex count, animation set size, and the animated joint position and rotation at three sample times. The bone chunk bytes are pinned by a test to the hand-built rig the engine loaded in the spike.
- Rules: bones are written parents-first with children contiguous; a synthetic `root` bone at the origin is added when the skin has several roots or the root is rotated more than about 8 degrees (the engine refuses such a skeleton); the root joint's animation keys are root motion in the engine and are replaced by its bind pose (with a warning); weights are 4 per vertex, u8, summing to 255.
- Refused with `SkinError` (exit 2, `gltf2chr: ...`): more than one skin, JOINTS_1/WEIGHTS_1, morph targets, cubic-spline animation, non-rigid (scaled) bind poses, more than 32767 vertices, a skinned primitive without NORMAL.
- The static `gltf2cgf` still refuses skinned input, as before.
- Not covered yet: LODs, physics proxies, per-vertex colours, scale animation beyond passing the key through, animations on non-joint nodes. A character was not drawn in the probe, so lighting and visuals are unproven (see the sandbox TASK-sandboxllm-mcp-24).

## 0.7.0 - 2026-10-27 - Fixture folders follow the Plasmid naming rule

- Game-relative fixture folders `Objects/snl_3p/...` and `Objects/snl_test/...` become `Objects/plasmid_3p/...` and `Objects/plasmid_test/...` in the schematyc-write default mesh (`DEFAULT_MESH_FILE`), the CLI help and the terrain brush docs. A host project must rename its own fixture folders to match (assets on disk are not touched by this tool).
- No other behaviour change.

## 0.6.0 - 2026-10-27 - Renamed to plasmid-assets

- Package `cry_assets` is now `plasmid_assets`. Import path: `from plasmid_assets import png`; module run: `python3 -m plasmid_assets`.
- Command `plas-assets`: an executable launcher at the repo root that resolves its own directory and runs the package from any working directory. The usage text reads `plas-assets`. Subcommands, flags, stdout and exit codes are unchanged.
- Fixture names (defaults and output names): `schematyc-write --name` default `snl_probe` -> `plasmid_probe`; `pfx-write` `snl_spark_<tag>` -> `plasmid_spark_<tag>` (.dds and .pfx); `audio-write` `snl_beep.wav` -> `plasmid_beep.wav`, `snl_test.xml` -> `plasmid_test.xml`, trigger `Play_snl_beep` -> `Play_plasmid_beep`, ATL name `snl_test` -> `plasmid_test`. The game-relative asset folders (`Objects/snl_test/uvquad.cgf`, `Objects/snl_3p/...`) are unchanged: they name on-disk assets.
- Test environment variable `CRY_REFERENCE_DIR` -> `PLASMID_ASSETS_REFERENCE_DIR`.
- Repo and VERSION: `plasmid-assets` (the repo is `Tools/plasmid-assets/`), VERSION 0.6.0. `.gitignore` gains local env, editor and secret files.
- Migration for vendoring consumers:
  1. Re-vendor the v0.6.0 tag into `tools/plasmid-assets/` (replace `tools/cry-assets/`; never edit the copy in place).
  2. Change imports `cry_assets` -> `plasmid_assets`, and `python3 -m cry_assets` -> `python3 -m plasmid_assets`, or call `tools/plasmid-assets/plas-assets`.
  3. Update any script that passes `--name snl_probe` or reads `snl_spark_*`, `snl_beep.wav` or `Play_snl_beep` to the `plasmid_` names above.
  4. Rename the environment variable `CRY_REFERENCE_DIR` to `PLASMID_ASSETS_REFERENCE_DIR` where it is set.

## 0.5.0

- `cgf-bounds <file.cgf> [--assets-dir D]`: the vertex AABB of a 0x746 .cgf as JSON (`{"file", "min", "max"}`), from
  `cgf_dump.mesh_bounds`. Exit 2 with `cgf-bounds: ...` on stderr when the file cannot be read. Read only.
- `terrain-sample --size N --heightmap {png:PATH,flat:Z,hills:SEED} --max-height M --points "x,y;x,y;..."`: the ground
  height at each point as JSON (`{"points": [{"x", "y", "z"}]}`). Every point must satisfy 0 <= x, y <= N, else exit 2.
  The height is read from the same quantised leaves the writer stores (`terrain.leaf_quantised`, now shared with
  `_write_node`), so it is the height the engine reads from terrain.dat, not the float source. Only the sectors the
  points need are computed (`OnDemandHeights`, `hills_u_at`, which equals `hills()` sample for sample).
- Ground model: `terrain.ground_height` follows `CTerrain::GetZApr` (`Code/CryEngine/Cry3DEngine/terrain_hmap.cpp`,
  lines 133 and 29): the unit cell (int(x), int(y)), its four corners from the leaf sector that owns the lower-left
  unit, triangulated with the diagonal from (x, y) to (x+1, y+1). It is not bilinear.
  Tolerance: the stored height differs from the float32 source sample by at most half the leaf step, span/8190 m of
  that leaf (tests/test_ground.py checks this bound). `terrain-sample` and the parser read-back of the written
  terrain.dat agree exactly (test_ground.py). Engine float32 arithmetic may differ by about 1e-4 m (not measured).
- Not the engine's behaviour in a running game (needs an engine run): the nUnitBitShift == 0 assumption (full
  detail codes at every distance), and the edges. `GetZApr` returns 0 for x <= 0 or y <= 0 and for points at or past
  the far edge; `terrain-sample` returns the clamped edge height there instead.
- Output bytes of terrain-write are unchanged (parity lines, the 2048 hills terrain.dat, and the level pins of the
  mcp tests).

## 0.4.0

- Release note: 0.3.0 (below) and 0.4.0 were developed and committed together in one change, sharing `terrain.py`, `cli.py`,
  the parity file and the tests. They are not separable without inventing an untested state, so the single tag `v0.4.0`
  carries both; there is no `v0.3.0` tag. The 0.3.0 entry below describes what 0.3.0 added and is part of this tag.
- Brushes in `terrain/terrain.dat`: `terrain_dat_bytes(..., brushes=None, assets_dir=None)` and `level_terrain_files`
  take a list of brushes (`cgf`, `pos`, optional `rot` quaternion, `scale`, `material_id`). Output with no brushes is
  byte-identical to 0.3.0 (parity lines unchanged).
- Brush table: one SNameChunk per distinct cgf, first-use order. Object block: one record per brush (int32 EERType 1 +
  100-byte SBrushChunk, `struct` format `BRUSH_CHUNK_FMT`, all offsets from the brush layout research, section 1), under
  the single childless root octree chunk; its objectsBlockSize is 104 per brush. The root chunk AABB is unchanged.
- The stored world AABB is the transformed 8 corners of the .cgf vertex bounds (`cgf_dump.mesh_bounds`, which reads the
  Mesh chunk's POSITIONS stream, float32 or half-float). A missing or unreadable .cgf is a ValueError (exit 2 in the CLI).
- Matrix: row-major 3x4 `[R * diag(scale) | pos]`, the translation at matrix indices 3, 7, 11. Scale composition (each
  column of R times the scale of that axis) is not in the research: unverified.
- Defaults, with sources. From the measured sample record (research section 1, V): layer id 22, shadow bias 0, view
  distance ratio 100, LOD ratio 100, dummy 0, collision class 0, material layers 0. From the research's explicit advice:
  render-node flags 0 and flags 0 (its sample flag word includes ERF_PENDING_DELETE, so it is not copied). Material id -1
  (the sample's value; the only accepted value, since the material table is written empty).
  OPEN QUESTION: layer id 22 is the sample's value, but the research's own minimal example uses 0 and marks the
  layer-0 behaviour U. The engine may treat the layer differently; an engine run should decide.
- Parser: `parse_terrain_dat` returns `brush_names`, `brush_records` (each with cgf, AABB, layer, type index, matrix,
  material id and the other fields) and `warnings`. Strict mode fails on structural faults; a brush AABB whose x or y
  lies outside `(0,0)-(heightmap size x unit)` is a warning in both modes (z is not checked). The strict rule for an empty octree chunk at EOF is now
  a rule for a block of whole records that ends at EOF.
- CLI: `terrain-write --brushes FILE --assets-dir DIR` (exit 2 when only one of the two is given, or on any brush
  error); the manifest gets a `brushes` key only when brushes are given; `terrain-check` prints the brush table size,
  the brush count and the warnings.
- Alignment: every brush table entry and record is a multiple of 4 bytes, so no 0xDE gap is written around the brush
  table or the object block. The research says nothing about alignment there; this follows from the sizes.
- Not in this version: vegetation groups (the parser still refuses a non-empty vegetation table, and its 368-byte
  StatInstGroupChunk constant is the research's open item 6, 364 bytes), child octree nodes, and any check of the
  material table names.
- Not verified: engine rendering, culling and collision of brushes; the layer id default; the z extent of the engine's
  root box; that the engine loads brushes from these bytes (needs an engine run).

## 0.3.0

(Released only inside `v0.4.0`; see the release note above.)

- Terrain files ported from the FPS asset pipeline (stdlib only, byte parity with the FPS writer, commit d131636):
  `cry_assets/terrain.py` (terrain.dat writer with the empty octree chunk and 0xDE gaps, strict and lenient parser,
  `level_terrain_files` for the size-dependent level files, `level_size_attributes` for the XML size fields,
  `make_cover_ctc` and the terraintexture pak, navmesh and vegetation stubs) and `cry_assets/heightmap.py`
  (heightmap.dat writer for sizes 512, 1024 and 2048, `from_png`, `flat`, and `hills`, a deterministic
  integer-hash value noise of our own).
- `png.read_png_gray` reads gray PNGs at full bit depth (1, 2, 4, 8 and 16 bit). `read_png` is unchanged.
- Subcommands: `terrain-write` (writes the level terrain file set and a sha256 manifest) and `terrain-check` (parses a
  terrain.dat and prints its structure; exit 0 or 1).
- Parity: tests/parity.sha256 gained 15 lines (terrain_, heightmap_, cover_ctc_): the FPS sha256 for 3 sizes and 3
  heightmap kinds (terrain.dat), the 512 heightmap.dat for the same kinds, and the cover.ctc member for 3 sizes.
  tests/test_terrain.py checks them; test_parity.py checks only its own names.
- Not parity-bound: the terraintexture pak member date is fixed (1980-01-01), where the FPS writer stamps the current time.
- Not verified: the engine loading a new-size level built from these files (needs an engine run); the template
  cover.ctc kept inside level.pak (it has a different layout from make_cover_ctc output).

## 0.2.0

- Fixture writers ported from the P0(c), P0(d) and P0(i) spike generators, with explicit output directories:
  `pfx` (PFX2 effect JSON and its BC3 texture), `schematyc` (`.schematyc_ent` entity class, with a mesh-path
  parameter in place of the spike's environment variable) and `audio` (440 Hz wav and ATL xml; the caller makes
  the project-root `audio` link, the writer does not).
- Subcommands: `pfx-write`, `schematyc-write`, `audio-write`. They print a JSON list of the written files.
- Output bytes match the spike generators for the same parameters (pfx and audio byte for byte; schematyc with a seeded
  `uuid4`, because its GUIDs are random per run).
- Tests for each writer and CLI smoke tests for the new subcommands.
- Content-hash cache (`cache` module), opt-in with `--cache-dir PATH` on `png2dds` and `gltf2cgf`. The key is the
  sha256 of the PNG bytes, format, srgb, mips, persistent, trailer and `__version__`. A hit copies the stored bytes;
  entries that are short, mis-headed or have the wrong length are ignored and rewritten. Writes go to a temporary
  name and are renamed into place. Without `--cache-dir` nothing is cached.
- `--jobs N` on `png2dds` (encodes block-row bands in worker processes) and `gltf2cgf` (encodes independent
  textures in a process pool). Default 1; 0 means all CPUs. Output is byte-identical for every job count.
- BC encoder: the colour palette distance and the alpha index search are inlined, with the same integer and float
  arithmetic and the same tie-breaking. No algorithm change; output bytes are unchanged.
- `dds.write_dds` takes an optional `jobs` argument (default 1). Its argument checks are in `dds.check_args`.
- `__main__.py` runs `main()` only under `if __name__ == "__main__"`, so spawned workers can import it.

## 0.1.0

- First port of the DDS, CGF and glTF tools from the P0(f) spike. Logic, tables, constants and output
  formatting are unchanged; only imports, module structure and CLI wiring changed.
- Modules: `png` (PNG reader), `dds` (DDS writer and decoder), `cgf` (static-mesh CGF writer), `cgf_dump`
  (CGF dumper), `gltf` (glTF/GLB importer), `cli` (subcommands).
- Subcommands: `png2dds`, `cgf-write`, `cgf-dump`, `gltf2cgf`.
- Stdlib only. Tests are unittest, with fixtures generated in-test.
