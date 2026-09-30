"""Generate and apply seamless cockpit/nozzle PBR maps through Blender MCP.

The hard-surface craft and planets already have packed PBR maps. This pass
finishes the two visible, UV-mapped craft materials still using flat values.
It is deterministic and safe to rerun on the saved Asterion scene.
"""

from pathlib import Path

import bpy
import numpy as np


ROOT = Path(__file__).resolve().parent / "advanced_spaceship" / "textures"
ROOT.mkdir(parents=True, exist_ok=True)
SIZE = 1024
axis = np.arange(SIZE, dtype=np.float32) / SIZE
x, y = np.meshgrid(axis, axis)
TAU = np.float32(np.pi * 2)


def harmonics(seed):
    rng = np.random.default_rng(seed)
    result = np.zeros((SIZE, SIZE), dtype=np.float32)
    for frequency, strength in ((3, .43), (7, .27), (17, .17), (43, .08)):
        a, b = rng.uniform(0, TAU, 2)
        result += strength * np.sin(TAU * frequency * x + a) * np.cos(
            TAU * (frequency + 2) * y + b)
    return result


def write_image(name, rgb, *, data=False):
    height, width, _ = rgb.shape
    rgba = np.ones((height, width, 4), dtype=np.float32)
    rgba[:, :, :3] = np.clip(rgb, 0, 1)
    image = bpy.data.images.new("ASTERION TEMP | " + name, width=width,
                                height=height, alpha=True)
    try:
        image.colorspace_settings.name = "Non-Color" if data else "sRGB"
        image.file_format = "PNG"
        image.filepath_raw = str(ROOT / name)
        image.pixels.foreach_set(rgba.ravel())
        image.save()
    finally:
        bpy.data.images.remove(image)


def normal_from_height(height, gain):
    dx = np.roll(height, -1, 1) - np.roll(height, 1, 1)
    dy = np.roll(height, -1, 0) - np.roll(height, 1, 0)
    nx, ny = -dx * gain, -dy * gain
    norm = np.sqrt(nx * nx + ny * ny + 1)
    return np.stack((nx / norm * .5 + .5,
                     ny / norm * .5 + .5,
                     1 / norm * .5 + .5), axis=2)


noise = harmonics(445)
fine = harmonics(1445)
glass_score = np.exp(-((np.sin(TAU * 16 * (x + .065*y))) / .055)**2)
glass_height = noise*.11 + fine*.025 - glass_score*.018
glass_tint = np.clip(.62 + noise*.25 + fine*.08 - glass_score*.13, 0, 1)
glass_albedo = np.stack((.065 + glass_tint*.10,
                         .13 + glass_tint*.18,
                         .19 + glass_tint*.24), axis=2)
glass_rough = np.clip(.22 + noise*.055 + fine*.025 + glass_score*.11,
                      .13, .44)
glass_metal = np.clip(.39 + noise*.08, .25, .52)
glass_ao = np.clip(.96 - glass_score*.055, .87, 1)

machining = np.sin(TAU * (25*x + 2*y))*.5 + np.sin(TAU * 56*y)*.16
heat = np.maximum(np.sin(TAU * (4*x-y)), 0)
nozzle_height = noise*.09 + fine*.03 + machining*.017
nozzle_albedo = np.stack((.035 + noise*.015 + heat*.08,
                          .075 + noise*.025 + heat*.035,
                          .13 + noise*.04 - heat*.025), axis=2)
nozzle_rough = np.clip(.31 + noise*.075 + machining*.035 + heat*.12,
                       .22, .58)
nozzle_metal = np.clip(.78 + noise*.09 - heat*.12, .59, .9)
nozzle_ao = np.clip(.95 + noise*.035, .86, 1)

families = (
    ("canopy", "04b | smoked iridium cockpit glazing", glass_albedo,
     glass_height, glass_ao, glass_rough, glass_metal, 7.0),
    ("nozzle", "05b | cobalt engine nozzle", nozzle_albedo,
     nozzle_height, nozzle_ao, nozzle_rough, nozzle_metal, 7.5),
)


def image_node(nodes, name, *, data):
    path = ROOT / name
    image = bpy.data.images.get(name)
    if image is None:
        image = bpy.data.images.load(str(path), check_existing=True)
    else:
        image.filepath = str(path)
        image.reload()
    image.name = name
    image.colorspace_settings.name = "Non-Color" if data else "sRGB"
    image.pack()
    image.filepath = "//advanced_spaceship/textures/" + name
    node = nodes.new("ShaderNodeTexImage")
    node.image = image
    node.label = "Asterion generated " + name
    return node


for family, material_name, albedo, height, ao, rough, metal, gain in families:
    write_image(f"{family}_albedo.png", albedo)
    write_image(f"{family}_normal.png", normal_from_height(height, gain),
                data=True)
    write_image(f"{family}_orm.png", np.stack((ao, rough, metal), axis=2),
                data=True)
    material = bpy.data.materials.get(material_name)
    if material is None:
        # Asset generation can precede a fresh scene build.
        continue
    if not material.use_nodes:
        raise RuntimeError(f"Material has no shader nodes: {material_name}")
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    for node in tuple(nodes):
        if node.label.startswith("Asterion generated "):
            nodes.remove(node)
    color = image_node(nodes, f"{family}_albedo.png", data=False)
    orm = image_node(nodes, f"{family}_orm.png", data=True)
    normal = image_node(nodes, f"{family}_normal.png", data=True)
    split = nodes.new("ShaderNodeSeparateColor")
    split.label = "Asterion generated ORM channels"
    bump = nodes.new("ShaderNodeNormalMap")
    bump.label = "Asterion generated normal map"
    bump.inputs["Strength"].default_value = .5
    links.new(color.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(orm.outputs["Color"], split.inputs["Color"])
    links.new(split.outputs["Green"], bsdf.inputs["Roughness"])
    links.new(split.outputs["Blue"], bsdf.inputs["Metallic"])
    links.new(normal.outputs["Color"], bump.inputs["Color"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    gltf_group = bpy.data.node_groups.get("glTF Material Output")
    if gltf_group:
        group = next((node for node in nodes
                      if node.type == "GROUP" and node.node_tree == gltf_group),
                     None)
        if group is None:
            group = nodes.new("ShaderNodeGroup")
            group.node_tree = gltf_group
        links.new(split.outputs["Red"], group.inputs["Occlusion"])

print("ASTERION_SURFACE_MAPS", [(family, material)
                                for family, material, *_ in families])
