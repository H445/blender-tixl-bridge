"""Run through Blender MCP in a disposable --background --factory-startup process.

Creates an isolated short textured scene, never opens or saves the interactive
user's scene. The cache and report stay under the ignored example cache.
"""
import json
import shutil
import sys
import traceback
import uuid
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "blender_tixl_bridge" / "source"))
import blend_sync
import blend_sync_graph


def main():
    folder = ROOT / "examples" / ".tixl_cache" / "cache_contract_smoke" / uuid.uuid4().hex
    folder.mkdir(parents=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 9
    scene.render.fps = 60
    scene["tixl_project_name"] = "CacheContractValidation"
    texture = folder / "texture.png"
    generated = bpy.data.images.new("ContractTexture", width=2, height=2)
    generated.pixels.foreach_set([0.1, 0.3, 0.8, 1.0] * 4)
    generated.filepath_raw, generated.file_format = str(texture), "PNG"
    generated.save()
    bpy.data.images.remove(generated)
    image = bpy.data.images.load(str(texture))
    material = bpy.data.materials.new("ContractMaterial")
    material.use_nodes = True
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    material.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    bpy.data.objects["Cube"].data.materials.clear()
    bpy.data.objects["Cube"].data.materials.append(material)
    blend = folder / "CacheContractValidation.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    source_sha = blend_sync.digest(blend)
    cache = folder / "cache"
    first = blend_sync.sync(blend, "generic", cache, Path(bpy.app.binary_path), False, False)
    first_glb_sha = blend_sync.digest(cache / "worlds" / "main_opaque.glb")
    second = blend_sync.sync(blend, "generic", cache, Path(bpy.app.binary_path), False, False)
    assert first["status"] == "rebuilt" and second["status"] == "up_to_date"
    assert blend_sync.digest(cache / "worlds" / "main_opaque.glb") == first_glb_sha
    # Change an external resource without saving or modifying the .blend.
    image.pixels.foreach_set([0.8, 0.2, 0.1, 1.0] * 4)
    image.save()
    assert blend_sync.digest(blend) == source_sha
    third = blend_sync.sync(blend, "generic", cache, Path(bpy.app.binary_path), False, False)
    assert third["status"] == "rebuilt"
    assert blend_sync.digest(cache / "worlds" / "main_opaque.glb") != first_glb_sha
    # A private graph-template change changes generated graph output while
    # exported geometry stays reusable. Production templates are untouched.
    private_templates = folder / "templates"
    shutil.copytree(blend_sync_graph.TEMPLATE, private_templates)
    ui_path = private_templates / "BridgeTemplate.t3ui"
    ui = json.loads(ui_path.read_text())
    ui["CacheContractValidation"] = True
    ui_path.write_text(json.dumps(ui))
    before_ui = next((cache / "native_source").glob("*.t3ui")).read_bytes()
    blend_sync_graph.TEMPLATE = private_templates
    fourth = blend_sync.sync(blend, "generic", cache, Path(bpy.app.binary_path), False, False)
    assert fourth["status"] == "up_to_date"
    assert next((cache / "native_source").glob("*.t3ui")).read_bytes() != before_ui
    report = {"status": "passed", "blenderVersion": bpy.app.version_string,
              "statuses": [result["status"] for result in (first, second, third, fourth)],
              "externalTextureRebuilt": True, "sourceBlendUnchanged": True,
              "graphOnlyChangeReusedGeometry": True, "fixture": str(folder)}
    (folder / "report.json").write_text(json.dumps(report, indent=2))
    print("CACHE_CONTRACT_SMOKE_OK " + json.dumps(report), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        # Blender otherwise exits successfully on a Python exception.
        import os
        os._exit(1)
