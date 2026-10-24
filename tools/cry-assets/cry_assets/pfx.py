"""Self-authored PFX2 particle-effect fixture (ported from the P0(d) spike make_pfx_fixture.py).

write_pfx(out_dir, png_path, tag) writes two files and returns their paths, DDS first:
  <out_dir>/Textures/snl_spark_<tag>.dds   BC3 texture from png_path (srgb=True)
  <out_dir>/particles/snl_spark_<tag>.pfx  plain JSON effect (no trailing commas), every key the engine's schema shows
The texture reference inside the .pfx is the game-relative string "Textures/snl_spark_<tag>.dds", whatever out_dir is.
The engine caches a failed lookup as null, so use a new tag for every variant within one game run.
"""

import json
import os

from .dds import write_dds
from .png import read_png


def effect_features(tag, tex):
    """Feature list for a tag. The first character selects the variant family (see the comments below)."""
    fx = [
        {"RenderSprites": {"SortMode": "None", "FacingMode": "Screen", "AspectRatio": 1.0, "SphericalProjection": 0.0,
                           "SortBias": 0.0, "CameraOffset": 0.0, "Offset": {"x": 0.0, "y": 0.0}, "FlipU": False,
                           "FlipV": False, "FillCost": 1.0}},
        {"SpawnRate": {"Amount": {"value": 20.0}, "Delay": {"value": 0.0}, "Duration": {"value": "Infinity"},
                       "Mode": "ParticlesPerSecond"}},
        {"LifeTime": {"LifeTime": {"value": 2.0}, "KillOnParentDeath": False}},
        {"FieldSize": {"value": {"value": 0.5}}},
        {"AppearanceMaterial": {"Material": "", "Texture": tex}},
    ]
    # variants (a new tag per variant: the engine caches failed lookups): "b*" adds a white FieldColor (without a colour
    # feature the sprite renders black, render check 2026-10-24); "c*" adds a spawn sphere and an upward velocity as well; "d*" = c + AppearanceLighting, "e*" = b + AppearanceLighting, "f*"/"g*" = e/d with FacingMode Camera
    if tag[0] in "bcdefg":
        fx.insert(4, {"FieldColor": {"Color": {"Color": {"r": 255, "g": 255, "b": 255, "a": 255}}}})
    if tag[0] in "cdg":
        fx.append({"LocationSphere": {"Radius": {"value": 0.5}, "InnerFraction": 1.0, "Velocity": {"value": 0.0},
                                      "AxisScale": {"x": 1.0, "y": 1.0, "z": 1.0}, "Distribution": "Random"}})
        fx.append({"VelocityDirectional": {"Velocity": {"x": 0.0, "y": 0.0, "z": 1.5}, "Scale": {"value": 1.0}}})
    if tag[0] in "defg":  # self-lit sprite: without an AppearanceLighting feature the sprites rendered black
        fx.append({"AppearanceLighting": {"Diffuse": 1.0, "BackLight": 1.0, "Emissive": 100.0, "Curvature": 0.0, "EnvironmentLighting": True,
                                          "ReceiveShadows": False, "AffectedByFog": True, "VolumeFog": False}})
    if tag[0] in "fg":  # "Camera" facing instead of "Screen"
        fx[0]["RenderSprites"]["FacingMode"] = "Camera"
    return fx


def write_pfx(out_dir, png_path, tag="a"):
    """Write the texture and the effect under out_dir; return [dds_path, pfx_path]."""
    tex = f"Textures/snl_spark_{tag}.dds"
    w, h, px = read_png(png_path)
    dds_path = os.path.join(out_dir, "Textures", f"snl_spark_{tag}.dds")
    os.makedirs(os.path.dirname(dds_path), exist_ok=True)
    write_dds(dds_path, w, h, px, "bc3", srgb=True)

    eff = {"Version": 13, "Attributes": {"Attributes": []},
           "Components": [{"Component": {"Name": "Component", "Stats": [], "nodePos": {"x": 0.0, "y": 0.0},
                                         "Features": effect_features(tag, tex)}}]}
    pfx_dir = os.path.join(out_dir, "particles")
    os.makedirs(pfx_dir, exist_ok=True)
    pfx_path = os.path.join(pfx_dir, f"snl_spark_{tag}.pfx")
    with open(pfx_path, "w") as f:
        f.write(json.dumps(eff, indent=1) + "\n")
    return [dds_path, pfx_path]
