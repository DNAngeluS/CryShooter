"""Is the game window actually rendering? Image and shader-cache health checks (pure Python, no display needed).

Used on screenshots taken from a running game, plus shader-cache counters:

  * analyze_image(source)      reduce an image (path or numpy array, full resolution) to a few numbers
  * evaluate_image(metrics)    turn those numbers into pass/fail with reason codes and warnings
  * check_shader_settle(...)   decide from shader-cache file counts whether compilation has finished
  * exit_code_for(status)      map a verdict to a process exit code
  * parse_capture_marker / count_log_signals / parse_wmctrl_windows   read the game log and window list
  * combine_verdicts(...)      one verdict from the parts of a health run (precedence in its docstring)

Nothing here launches a process or touches a display. NumPy and Pillow are needed only by analyze_image();
importing this module works without them.
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # only a flag: the functions that need numpy/Pillow import them lazily
    import numpy  # noqa: F401
    import PIL  # noqa: F401
    HAVE_IMAGING = True
except ImportError:
    HAVE_IMAGING = False

# Values come from real baselines: Intel and NVIDIA captures of a rendering game window gave
# p99 luma 196.7-197.0, luma std 18.1-30.1, near_black 0.002-0.003 and 242-508 distinct colours (4-bit).
THRESHOLDS: dict = {
    "min_width": 320,
    "min_height": 240,
    "min_alpha_mean": 0.99,
    "black_p99_luma": 12.0,
    "mostly_black_luma": 8.0,
    "mostly_black_frac": 0.98,
    "uniform_std": 6.0,
    "uniform_distinct": 48,
    "colour_drift": 12.0,
}


def _imaging():
    """Import numpy and Pillow, or fail with the message every caller of analyze_image() relies on."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("numpy and Pillow are required for image analysis") from exc
    return np, Image


def analyze_image(source) -> dict:
    """Metrics for an image given as a file path (str/Path) or a numpy array (H,W,3 or H,W,4; uint8 or float 0-255)."""
    np, Image = _imaging()
    if isinstance(source, (str, Path)):
        with Image.open(source) as im:
            # keep alpha only when the file has it; everything else is plain RGB
            has_alpha = "A" in im.getbands() or "transparency" in im.info
            arr = np.asarray(im.convert("RGBA" if has_alpha else "RGB"))
    else:
        arr = np.asarray(source)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(f"expected an (H, W, 3) or (H, W, 4) image, got shape {arr.shape}")

    rgb = np.clip(arr[..., :3].astype(np.float64), 0, 255)
    # Luma is the plain mean of R, G and B (the convention of the baselines above). It cannot see a
    # red/blue swap, which is what channel_means is for.
    luma = rgb.mean(axis=2)
    alpha_mean = None
    if arr.shape[2] == 4:
        alpha_mean = float(arr[..., 3].astype(np.float64).mean() / 255.0)

    # 4-bit quantisation per channel, packed into one integer per pixel so np.unique is cheap
    q = np.rint(rgb).astype(np.uint32) >> 4
    code = (q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]

    return {
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "alpha_mean": alpha_mean,
        "mean_luma": float(luma.mean()),
        "p99_luma": float(np.percentile(luma, 99)),
        "std_luma": float(luma.std()),
        "near_black_frac": float((luma < THRESHOLDS["mostly_black_luma"]).mean()),
        "distinct_colors": int(np.unique(code).size),
        "channel_means": {
            "r": float(rgb[..., 0].mean()),
            "g": float(rgb[..., 1].mean()),
            "b": float(rgb[..., 2].mean()),
        },
    }


def evaluate_image(metrics: dict, thresholds: dict = THRESHOLDS, reference_rgb: tuple | None = None) -> dict:
    """Verdict for analyze_image() metrics. Every applicable failure is listed; `reason` is the first one."""
    t = thresholds
    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []

    w, h = metrics["width"], metrics["height"]
    if w < t["min_width"] or h < t["min_height"]:
        failures.append(("too-small", f"image is {w}x{h}, below the {t['min_width']}x{t['min_height']} minimum"))

    alpha = metrics["alpha_mean"]
    if alpha is not None and alpha < t["min_alpha_mean"]:
        failures.append(("transparent", f"alpha mean {alpha:.3f} < {t['min_alpha_mean']}: window is not opaque"))

    p99 = metrics["p99_luma"]
    if p99 < t["black_p99_luma"]:
        failures.append(("black", f"p99 luma {p99:.1f} < {t['black_p99_luma']}: frame is black"))

    frac = metrics["near_black_frac"]
    if frac > t["mostly_black_frac"]:
        failures.append(("mostly-black", f"{frac:.1%} of pixels have luma < {t['mostly_black_luma']} "
                                         f"(limit {t['mostly_black_frac']:.0%})"))

    std, distinct = metrics["std_luma"], metrics["distinct_colors"]
    if std < t["uniform_std"] or distinct < t["uniform_distinct"]:
        failures.append(("uniform", f"luma std {std:.2f} (min {t['uniform_std']}), {distinct} distinct colours "
                                    f"(min {t['uniform_distinct']}): flat frame"))

    if reference_rgb is not None:
        means = metrics["channel_means"]
        dev = {c: means[c] - ref for c, ref in zip("rgb", reference_rgb)}
        worst = max(abs(d) for d in dev.values())
        if worst > t["colour_drift"]:
            warnings.append(("colour-drift",
                             f"channel means r={means['r']:.1f} g={means['g']:.1f} b={means['b']:.1f} vs reference "
                             f"{tuple(reference_rgb)}: largest deviation {worst:.1f} > {t['colour_drift']} "
                             f"(red/blue swap?)"))

    messages = [m for _, m in failures + warnings]
    return {
        "status": "fail" if failures else "pass",
        "reason": failures[0][0] if failures else None,
        "message": "; ".join(messages) if messages else "frame looks rendered",
        "failures": [code for code, _ in failures],
        "warnings": [code for code, _ in warnings],
    }


def check_shader_settle(files_a: int, files_b: int, cold_files: int, cache_miss: int, crc_mismatch: int) -> dict:
    """Whether the active shader-cache slot has stopped changing. files_a/files_b: counts a few seconds apart.

    Not based on the shaders-status idle verdict: that reads "still compiling" until ~60 s after launch
    even on a warm cache.
    """
    counts = f"files {files_a} -> {files_b} (cold below {cold_files}), cache misses {cache_miss}, " \
             f"crc mismatches {crc_mismatch}"
    if files_b < cold_files:
        return {"settled": False, "reason": "cache-cold", "message": f"shader cache is cold: {counts}"}
    if files_b != files_a or cache_miss > 0 or crc_mismatch > 0:
        return {"settled": False, "reason": "shaders-still-compiling", "message": f"shaders still compiling: {counts}"}
    return {"settled": True, "reason": None, "message": f"shader cache settled: {counts}"}


def exit_code_for(status: str) -> int:
    """pass -> 0, fail -> 1, anything else -> 2. A skipped check is never reported as a pass."""
    return {"pass": 0, "fail": 1}.get(status, 2)


def parse_capture_marker(text: str, saved_re: str, failed_re: str) -> dict:
    """In-engine screenshot marker in a log slice. The LAST marker (saved or failed) in the text wins.

    state: "saved" (file written, bytes > 0), "failed" (a failed marker, or a saved marker with 0 bytes),
    or "pending" (no marker). path/bytes/reason are None unless the state needs them.
    """
    found = []  # (position in text, state, path, bytes, reason)
    for m in re.finditer(saved_re, text):
        size = int(m.group("bytes"))
        if size > 0:
            found.append((m.start(), "saved", m.group("path"), size, None))
        else:
            found.append((m.start(), "failed", m.group("path"), size, "zero-byte screenshot"))
    for m in re.finditer(failed_re, text):
        found.append((m.start(), "failed", None, None, m.group("reason").strip()))
    if not found:
        return {"state": "pending", "path": None, "bytes": None, "reason": None}
    _, state, path, size, reason = max(found, key=lambda f: f[0])
    return {"state": state, "path": path, "bytes": size, "reason": reason}


def count_log_signals(text: str) -> dict:
    """Counts of lines that mean trouble in a game log slice. Informational: never decides a verdict alone."""
    lines = text.splitlines()
    return {
        "asserts": sum("[Assert]" in ln for ln in lines),
        "errors": sum("[Error]" in ln for ln in lines),
        "staging_buffer_assert": "Cannot create staging buffer" in text,
        "cache_miss": sum("global cache miss" in ln.lower() for ln in lines),
        "crc_mismatch": sum("crc mismatch" in ln.lower() for ln in lines),
    }


def parse_wmctrl_windows(output: str, pid: int) -> list[str]:
    """Window ids of the `wmctrl -lp` rows whose PID column is `pid`. Row: `0x04800002  1 1319592 host Title...`."""
    ids = []
    for line in output.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 3 and parts[2] == str(pid) and parts[0].startswith("0x"):
            ids.append(parts[0])
    return ids


def combine_verdicts(process: dict | None, shaders: dict | None, engine: dict | None, window: dict | None,
                     capture_error: str | None) -> dict:
    """One verdict from the parts of a health run. Precedence, the first matching rule wins:

      1. process = {"running": False, ...}                 -> fail not-running (no image can be trusted)
      2. shaders = check_shader_settle() result, unsettled -> fail with its reason (cache-cold / shaders-still-compiling)
      3. engine and window both evaluate_image() results:
           engine fail, window pass -> fail engine-capture-broken (the window shows the game is fine)
           engine pass, window fail -> fail with the window's reason
           both fail                -> fail with the engine's reason
           both pass                -> pass
         method "both" in every case
      4. one image result only      -> its verdict; method "in-engine" or "window"
      5. capture_error set, no image -> fail with its code (the text before the first ':', e.g. capture-timeout)
      6. nothing at all             -> status "error", reason cannot-capture. Never a pass.

    capture_error does not change a pass in rule 4: it is appended to the message as a note.
    """
    def result(status: str, reason: str | None, message: str, method: str | None) -> dict:
        return {"status": status, "reason": reason, "message": message, "method": method}

    if process is not None and not process.get("running", True):
        return result("fail", "not-running", process.get("detail") or "the game is not running", None)
    if shaders is not None and not shaders.get("settled", True):
        return result("fail", shaders.get("reason") or "shaders-still-compiling",
                      shaders.get("message", "shader cache not settled"), None)

    if engine is not None and window is not None:
        if engine["status"] == "fail" and window["status"] == "pass":
            return result("fail", "engine-capture-broken",
                          f"in-engine capture is broken ({engine['reason']}: {engine['message']}); "
                          f"the window capture is fine", "both")
        if engine["status"] == "pass" and window["status"] == "fail":
            return result("fail", window["reason"], f"window capture: {window['message']}", "both")
        if engine["status"] == "fail":
            return result("fail", engine["reason"], f"in-engine capture: {engine['message']}", "both")
        return result("pass", None, "in-engine and window captures look rendered", "both")

    if engine is not None or window is not None:
        image, method = (engine, "in-engine") if engine is not None else (window, "window")
        message = image["message"]
        if image["status"] == "pass":
            if capture_error:
                message += f" (note: {capture_error})"
            return result("pass", None, message, method)
        return result("fail", image["reason"], message, method)

    if capture_error:
        return result("fail", capture_error.split(":", 1)[0].strip(), capture_error, None)
    return result("error", "cannot-capture", "nothing was captured or checked", None)
