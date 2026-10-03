# DDS Normal Map Format Requirements (`_ddn.dds`)

> **Read this when:** The log says "Wrong format … for normal map texture", or you are adding `_ddn` textures.
> **Related:** [Known issues](known-issues.md) · [All docs](README.md)

## The Problem

CryEngine 5.6 requires that any texture whose filename ends with `_ddn` uses a
**two-channel compressed normal-map format**.  The engine checks this at load time in
`CTexture::Load` (`RenderDll/Common/Textures/Texture.cpp:1186`):

```cpp
if (!(m_eFlags & FT_ALPHA) && !(
      pImage->mfGetFormat() == eTF_BC5U || pImage->mfGetFormat() == eTF_BC5S ||
      pImage->mfGetFormat() == eTF_BC7  ||
      pImage->mfGetFormat() == eTF_EAC_RG11 || pImage->mfGetFormat() == eTF_EAC_RG11S
      ) && CryStringUtils::stristr(name, "_ddn") != 0 && GetDevTexture())
{
    gEnv->pSystem->Warning(..., "Wrong format '%s' for normal map texture '%s'",
                           CTexture::GetFormatName(), name);
}
```

Five engine-supplied textures shipped in **DXT1/BC1** format (a three-channel colour
format) instead of **BC5/ATI2** (the two-channel normal-map format the engine expects):

| Texture | Resolution | Impact |
|---------|-----------|--------|
| `%engine%/engineassets/textures/perlinnoisenormal_ddn.dds` | 256×256 | Perlin noise detail normals |
| `%engine%/engineassets/textures/oceanwaves_ddn.dds`        | 256×256 | Ocean surface waves         |
| `%engine%/engineassets/textures/screenfrost_ddn.dds`       | 512×512 | Screen frost overlay        |
| `%engine%/engineassets/textures/hex_ddn.dds`               | 128×128 | Hex-pattern surface detail  |
| `%engine%/engineassets/textures/glass_decalatlas_ddn.dds`  | 4096×2048 | Glass decal atlas normals |

Each texture triggers `[Warning] Wrong format 'Unknown' for normal map texture` on every
engine start and falls back to the error texture, degrading surface normal quality for the
affected shaders.

> **Why the format name shows "Unknown":** At the point the warning fires, `m_eDstFormat`
> on the `CTexture` object has not yet been set for the current load — it retains its
> previous value or the default `eTF_Unknown`.  The actual loaded format is BC1 (DXT1),
> which is valid but not acceptable for `_ddn` slots.

---

## Format Reference

| FourCC | CryEngine name | Channels | Bytes/block | Use |
|--------|---------------|----------|-------------|-----|
| `DXT1` | `eTF_BC1`     | RGB (3ch)   | 8  | Colour/diffuse |
| `DXT5` | `eTF_BC3`     | RGBA (4ch)  | 16 | Colour+alpha    |
| `ATI1` | `eTF_BC4U`    | R (1ch)     | 8  | Single-channel masks |
| `ATI2` | `eTF_BC5U`    | RG (2ch)    | 16 | **Normal maps** (`_ddn`) |

All block sizes are per 4×4 texel block.

### Normal Map Channel Convention (CryEngine)

```
R → Normal X component  (tangent-space, [-1..1] remapped to [0..255])
G → Normal Y component  (tangent-space, [-1..1] remapped to [0..255])
Z → derived at runtime: Z = sqrt(1 - X² - Y²)
```

BC5 stores R and G in two independent BC4 sub-blocks.  Z is never stored on disk.

---

## Linux Port Note: Lowercase Copies vs. PascalCase Originals

The Linux port (`5.6.7-linux-gcc9`) creates **separate lowercase DDS files** (not
symlinks) alongside the PascalCase originals so the case-sensitive filesystem can
resolve the engine's built-in PascalCase asset paths:

```
Engine/EngineAssets/Textures/
    perlinNoiseNormal_ddn.dds    ← original (DXT1, 43 KB)   — Windows loads this
    perlinnoisenormal_ddn.dds    ← Linux copy (ATI2, 85 KB) — Linux loads this
```

Only the lowercase copies are loaded at runtime on Linux; fixing them is sufficient
for eliminating the log warnings on this platform.  The PascalCase originals remain
DXT1 for Windows compatibility.  Use `--scan` (see below) if you also want to convert
the PascalCase originals.

Additional `_ddn.dds` files in the engine tree that the tested levels did **not**
exercise (no warning in `game.log`), but which are also DXT1 and would trigger the
same warning if loaded:

| File | Size | Notes |
|------|------|-------|
| `perlinNoiseNormal_ddn.dds` | 43 KB | PascalCase original of the fixed lowercase copy |
| `scratch_ddn.dds`           | 171 KB | Surface scratch normal — not used by current levels |
| `hiteffect_blurmask_ddn.dds`| 171 KB | Hit-effect blur normal — not used by current levels |
| `white_ddn.dds` / `White_ddn.dds` | 152 B | 1×1 flat-normal placeholder — negligible impact |

---

## The Fix

**Tool:** `tools/asset_pipeline/dds_normalmap_fix.py`

Converts DXT1 DDS files to BC5/ATI2 in place:

1. Reads the DXT1 DDS header (FourCC, width, height, mip count).
2. Decodes each mip level from DXT1 to RGB pixels.
3. Extracts the R and G channels (X and Y normal components).
4. Re-encodes each mip level as BC5/ATI2 (two independent BC4 blocks per 4×4 region).
5. Writes a new DDS header with FourCC `ATI2` and the re-encoded mip chain.

The B channel (Z) is discarded — it is not stored in BC5 and is always reconstructed
at runtime.

---

## Running the Converter

### One-shot: fix the five known engine assets

```bash
python3 tools/asset_pipeline/dds_normalmap_fix.py \
    --engine-dir /path/to/CRYENGINE
```

### Dry-run (check without modifying)

```bash
python3 tools/asset_pipeline/dds_normalmap_fix.py \
    --engine-dir /path/to/CRYENGINE --dry-run
```

### Fix specific files

```bash
python3 tools/asset_pipeline/dds_normalmap_fix.py \
    --files Engine/EngineAssets/Textures/oceanwaves_ddn.dds \
            Engine/EngineAssets/Textures/hex_ddn.dds
```

### Scan an entire directory tree

```bash
python3 tools/asset_pipeline/dds_normalmap_fix.py \
    --scan /path/to/CRYENGINE/Engine
```

This finds every `*_ddn.dds` that is currently DXT1 and converts it.  Files already
in ATI2/BC5 are skipped automatically.

---

## Integrating into the Build Pipeline

Import the module and call `fix_engine_ddns` once at the start of a build or as a
post-checkout hook:

```python
from pathlib import Path
from asset_pipeline.dds_normalmap_fix import fix_engine_ddns, scan_dxt1_ddns

ENGINE_DIR = Path("/path/to/CRYENGINE")

# Fix all known broken engine assets
results = fix_engine_ddns(ENGINE_DIR, verbose=True)
if any(r.error for r in results):
    raise RuntimeError("DDS normal-map conversion failed — check output above")

# Or scan the full engine tree to catch any additional ones
broken = scan_dxt1_ddns(ENGINE_DIR / "Engine")
for path in broken:
    fix_engine_ddns(path, verbose=True)
```

### Recommended hook point

Add this step **before the engine is launched** in any CI or local build script that
does a fresh checkout of the engine.  The five affected files are in the engine repo, not
in project assets, so the fix must target `CRYENGINE_DIR`, not the game project directory.

Example addition to a build script:

```bash
echo "Fixing DDS normal map formats..."
python3 "$FPS_PROJECT/tools/asset_pipeline/dds_normalmap_fix.py" \
    --engine-dir "$CRYENGINE_DIR"
```

---

## File Size Impact

BC5/ATI2 stores two channels versus DXT1's three, but uses twice as many bytes per
block (16 vs 8).  Expect output files to be roughly **2× larger** than the DXT1 originals:

| File | Before | After |
|------|--------|-------|
| `perlinnoisenormal_ddn.dds` | 42 KB  | 85 KB  |
| `oceanwaves_ddn.dds`        | 42 KB  | 85 KB  |
| `screenfrost_ddn.dds`       | 170 KB | 341 KB |
| `hex_ddn.dds`               | 10 KB  | 21 KB  |
| `glass_decalatlas_ddn.dds`  | 5.3 MB | 10.7 MB |

Total engine asset growth: ~5.6 MB — negligible relative to the engine's total asset size.

---

## Dependencies

The converter uses only Python standard library + `numpy` (already required by the
broader asset pipeline).  No external texture tools (`nvcompress`, `texconv`, etc.) are
needed.

```
numpy >= 1.20
```
