"""Derive aligned technical PBR maps from the GPT-generated albedo sources.

Run inside Blender through the official Blender MCP TCP extension. The five
albedo inputs are authored images; normals and packed occlusion/roughness/
metallic maps are deterministic technical derivatives, not additional art.
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
import numpy as np


TEXTURES = Path(__file__).resolve().parent / "textures"
SOURCES = {
    "hull": ("armor_graphite.png", .42, .78, 7.0),
    "carbon": ("carbon_albedo.png", .62, .08, 8.0),
    "copper": ("heat_titanium.png", .38, .91, 7.5),
    "solar": ("solar_ceramic.png", .32, .24, 5.0),
    "moon": ("moon_albedo.png", .88, .0, 11.0),
}


def smooth(image, passes=3):
    result = image
    for _ in range(passes):
        result = (4*result + np.roll(result, 1, 0)
                  + np.roll(result, -1, 0)
                  + np.roll(result, 1, 1)
                  + np.roll(result, -1, 1)) / 8
    return result


def save_map(name, rgb):
    height, width, _ = rgb.shape
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(rgb, 0, 1)
    rgba[:, :, 3] = 1
    image = bpy.data.images.new(name, width=width, height=height, alpha=True)
    try:
        image.colorspace_settings.name = "Non-Color"
        image.file_format = "PNG"
        image.filepath_raw = str(TEXTURES / name)
        image.pixels.foreach_set(rgba.ravel())
        image.save()
    finally:
        bpy.data.images.remove(image)


result = {}
for family, (source_name, roughness_base, metallic_base, normal_gain) in SOURCES.items():
    source_path = TEXTURES / source_name
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    image = bpy.data.images.load(str(source_path), check_existing=False)
    try:
        width, height = map(int, image.size)
        pixels = np.empty(width*height*4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgb = pixels.reshape(height, width, 4)[:, :, :3]
        luminance = (rgb[:, :, 0]*.2126 + rgb[:, :, 1]*.7152
                     + rgb[:, :, 2]*.0722)
        low_frequency = smooth(luminance, 6)
        high_frequency = luminance-low_frequency
        height_map = .60*smooth(luminance, 1) + .40*luminance
        dx = np.roll(height_map, -1, 1)-np.roll(height_map, 1, 1)
        dy = np.roll(height_map, -1, 0)-np.roll(height_map, 1, 0)
        nx = -dx*normal_gain
        ny = -dy*normal_gain
        nz = np.ones_like(nx)
        length = np.sqrt(nx*nx + ny*ny + nz*nz)
        normal = np.stack((nx/length*.5+.5, ny/length*.5+.5,
                           nz/length*.5+.5), axis=2)
        cavity = np.clip(.93 + high_frequency*1.65, .62, 1)
        roughness = np.clip(roughness_base-high_frequency*.55
                            + (1-luminance)*.055, .08, .98)
        if family == "solar":
            metallic = np.clip(.15 + np.maximum(luminance-.32, 0)*.58,
                               .12, .58)
        elif family == "moon":
            metallic = np.zeros_like(luminance)
        else:
            metallic = np.clip(metallic_base+high_frequency*.18, 0, 1)
        orm = np.stack((cavity, roughness, metallic), axis=2)
        save_map(f"{family}_normal.png", normal)
        save_map(f"{family}_orm.png", orm)
        result[family] = {"source": source_name, "size": [width, height],
                          "normal": f"{family}_normal.png",
                          "orm": f"{family}_orm.png"}
    finally:
        bpy.data.images.remove(image)

print("ASTERION_PBR_MAPS " + json.dumps(result, sort_keys=True))
