"""Regression checks for editable TiXL timing and replaceable Blender imports."""
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"))
from blend_sync_graph import generate  # noqa: E402
from blend_sync_project import _build_home, _link_world_clips, create_scaffold, populate, project_name_for  # noqa: E402


class SyncProjectTest(unittest.TestCase):
    def test_saved_scene_name_creates_exact_project_and_rejects_collision(self):
        import blend_sync
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / 'Operators'
            template.mkdir()
            (template / 'Operators.csproj').write_text(
                '<Project><RootNamespace>X</RootNamespace><HomeGuid>X</HomeGuid>'
                '<PackageId>X</PackageId></Project>')
            for index in range(2):
                blend = root / f'Source{index}.blend'
                blend.write_bytes(b'scene')
                cache = root / f'cache{index}'
                cache.mkdir()
                (cache / 'camera_timeline.json').write_text(json.dumps({
                    'shots': [{'id': 1, 'start': 0, 'label': 'Cube'}], 'passages': []}))
                manifest = {'fps': 60, 'project_name': 'BlendShapeExample',
                    'source_blend': str(blend), 'source_sha256': blend_sync.digest(blend),
                    'worlds': [{'world': 'cube', 'active_clip': [1, 241],
                                'opaque_count': 1, 'glass_count': 0, 'glbs': {'opaque': ''}}]}
                (cache / 'worlds').mkdir()
                for filename in ('cube_opaque.glb', 'cube_animation.bin'):
                    (cache / 'worlds' / filename).write_bytes(b'data')
                (cache / 'camera_60hz.bin').write_bytes(b'camera')
                stage = root / f'stage{index}'
                cache.rename(stage)
                cache.mkdir()
                manifest = blend_sync.publish(stage, cache, manifest, 'generic')
                files = generate(blend, cache, manifest)
                with patch.object(blend_sync, 'TIXL_PROJECT', template), patch.object(blend_sync, 'TIXL_EDITOR', root):
                    if index:
                        with self.assertRaises(FileExistsError):
                            blend_sync.ensure_generic_project(blend, cache, files, build=False)
                    else:
                        blend_sync.ensure_generic_project(blend, cache, files, build=False)
                        state = json.loads((cache / 'tixl_project.json').read_text())
                        self.assertEqual(state['name'], 'BlendShapeExample')
                        self.assertEqual(Path(state['path']), root / 'BlendShapeExample')

    def test_explicit_project_name(self):
        blend = Path('BlendShapeExample.blend')
        self.assertEqual(project_name_for(blend, 'BlendShapeExample'), 'BlendShapeExample')
        self.assertTrue(project_name_for(blend).startswith('Blend'))
        for invalid in ('../Other', 'Two Words', '2Example', 'CON', 'aux', 'LPT1', 'class'):
            with self.subTest(name=invalid), self.assertRaises(ValueError):
                project_name_for(blend, invalid)

    def test_import_filename_does_not_remove_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / 'BlendShapeExample.blend'
            blend.write_bytes(b'scene')
            cache = root / 'cache'
            cache.mkdir()
            (cache / 'camera_timeline.json').write_text(json.dumps({
                'shots': [{'id': 1, 'start': 0, 'label': 'Cube'}], 'passages': []}))
            files = generate(blend, cache, {'fps': 60, 'worlds': [
                {'world': 'cube', 'active_clip': [1, 241],
                 'opaque_count': 1, 'glass_count': 0}]})
            name = files[0].stem
            template = root / 'template'
            template.mkdir()
            (template / 'Template.csproj').write_text(
                '<Project><RootNamespace>X</RootNamespace><HomeGuid>X</HomeGuid>'
                '<PackageId>X</PackageId></Project>')
            project = root / 'project'
            create_scaffold(project, name, template, blend)
            for _ in range(2):
                populate(project, files, root / 'backups', root, build=False)
                home = json.loads((project / 'Symbols' / (name + '.t3')).read_text())
                self.assertNotEqual(home['Id'], json.loads(files[0].read_text())['Id'])
                self.assertTrue((project / 'Symbols' / (name + '.cs')).is_file())

    def test_home_clips_survive_resync(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blend = root / "Dance.blend"
            blend.write_bytes(b"saved scene")
            cache = root / "cache"
            cache.mkdir()
            (cache / "camera_timeline.json").write_text(json.dumps({
                "shots": [
                    {"id": 1, "start": 0, "label": "01 | Opening"},
                    {"id": 2, "start": 13, "label": "02 | Spin"},
                ],
                "passages": [],
            }))
            manifest = {"fps": 60, "worlds": [
                {"world": "opening", "active_clip": [1, 781], "opaque_count": 1, "glass_count": 0},
                {"world": "spin", "active_clip": [781, 1681], "opaque_count": 1, "glass_count": 0},
            ]}
            files = generate(blend, cache, manifest)
            generated = files + [cache / "native_source" / "graph_summary.json"]
            old_stamp = time.time_ns() - 10_000_000_000
            for path in generated:
                os.utime(path, ns=(old_stamp, old_stamp))
            generate(blend, cache, manifest)
            self.assertTrue(all(path.stat().st_mtime_ns == old_stamp for path in generated))
            graph = json.loads(files[0].read_text())
            self.assertEqual(len(graph["Animator"]), 0)
            self.assertFalse(any("laboratory" in child["Name"].lower()
                                 for child in graph["Children"]))
            template = root / "template"
            template.mkdir()
            (template / "Template.csproj").write_text(
                "<Project><RootNamespace>X</RootNamespace><HomeGuid>X</HomeGuid>"
                "<PackageId>X</PackageId></Project>")
            project = root / "project"
            create_scaffold(project, "DanceProject", template, blend)
            populate(project, files, root / "backups", root, build=False)
            home_path = project / "Symbols" / "DanceProject.t3"
            home = json.loads(home_path.read_text())
            scene_path = project / "Symbols" / "DanceProjectScene.t3"
            scene = json.loads(scene_path.read_text())
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderMeshSelect")
                                 for child in scene["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderMeshReplace")
                                 for child in scene["Children"]), 2)
            self.assertFalse(any(child["SymbolId"] == scene["Id"] for child in home["Children"]))
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderMeshSelect")
                                 for child in home["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderMeshReplace")
                                 for child in home["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderTextureSelect")
                                 for child in home["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderTextureReplace")
                                 for child in home["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderWorldClipTime")
                                 for child in home["Children"]), 2)
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderClipSequence")
                                 for child in home["Children"]), 3)
            world_sequences = {child["Id"] for child in home["Children"]
                               if child["Name"].endswith(" / clips")}
            routers = {child["Id"] for child in home["Children"]
                       if child["SymbolName"].endswith("BlenderWorldClipTime")}
            self.assertEqual(sum(edge["TargetParentOrChildId"] in world_sequences
                                 and edge["TargetSlotId"] == "36bf79ae-84ac-5691-b8cb-a65d2e055d1a"
                                 for edge in home["Connections"]), 2)
            self.assertEqual(sum(edge["SourceParentOrChildId"] in routers
                                 and edge["TargetSlotId"] == "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7"
                                 for edge in home["Connections"]), 2)
            self.assertEqual(sum(edge["SourceParentOrChildId"] in world_sequences
                                 and edge["SourceSlotId"] == "8ac94bb7-59c9-486b-9f8a-47e0ec25110e"
                                 and edge["TargetParentOrChildId"] in routers
                                 for edge in home["Connections"]), 2)
            self.assertTrue(any(child["SymbolName"].endswith("ToneMapping")
                                for child in home["Children"]))
            self.assertEqual(len({child["Id"] for child in home["Children"]}), len(home["Children"]))
            self.assertFalse({child["Id"] for child in home["Children"]}
                             & {child["Id"] for child in scene["Children"]})
            self.assertTrue(any(edge["SourceSlotId"] == "f5d218bb-d055-5800-9971-db0f88b6ead3"
                                for edge in home["Connections"]))
            preloads = [child for child in home["Children"]
                        if child["SymbolName"].endswith("BlenderWorldPreload")]
            self.assertEqual(len(preloads), 1)
            preload_id = preloads[0]["Id"]
            self.assertEqual(sum(edge["TargetParentOrChildId"] == preload_id
                                 and edge["TargetSlotId"] == "ebcd2d78-2b80-4b36-bd74-d074868b86dc"
                                 for edge in home["Connections"]), 2)
            self.assertTrue(any(edge["TargetParentOrChildId"] == preload_id
                                and edge["TargetSlotId"] == "8bf57a9c-25a2-4a41-a349-4a1769ff904b"
                                for edge in home["Connections"]))
            self.assertTrue(any(edge["SourceParentOrChildId"] == preload_id
                                and edge["SourceSlotId"] == "507e7775-3442-4271-a7fe-6cfa86462e22"
                                for edge in home["Connections"]))
            clips = [child for child in home["Children"]
                     if child["SymbolName"].endswith("BlenderSourceClip")]
            self.assertEqual([child["Name"] for child in clips], ["01 / Opening", "02 / Spin"])

            # Recover a pre-lane home after TiXL has changed the IDs and the
            # user has renamed both the global sequence and source clips.
            legacy_home = copy.deepcopy(home)
            legacy_ui = json.loads((project / "Symbols" / "DanceProject.t3ui").read_text())
            lane_ids = world_sequences | routers
            motion_targets = [edge["TargetParentOrChildId"] for edge in legacy_home["Connections"]
                              if edge["SourceParentOrChildId"] in routers
                              and edge["TargetSlotId"] == "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7"]
            legacy_home["Children"] = [child for child in legacy_home["Children"]
                                       if child["Id"] not in lane_ids]
            legacy_home["Connections"] = [edge for edge in legacy_home["Connections"]
                                          if edge["SourceParentOrChildId"] not in lane_ids
                                          and edge["TargetParentOrChildId"] not in lane_ids]
            legacy_ui["SymbolChildUis"] = [item for item in legacy_ui["SymbolChildUis"]
                                           if item["ChildId"] not in lane_ids]
            timeline_id = next(child["Id"] for child in legacy_home["Children"]
                               if child["SymbolName"].endswith("BlenderCameraTimeline"))
            for target in motion_targets:
                legacy_home["Connections"].append({
                    "SourceParentOrChildId": timeline_id,
                    "SourceSlotId": "dcc2da87-6bd5-5e0b-87ac-2cb31a95ee76",
                    "TargetParentOrChildId": target,
                    "TargetSlotId": "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7",
                })
            old_global = next(child for child in legacy_home["Children"]
                              if child["Name"] == "Edit move timing here")
            renamed = {old_global["Id"]: "84503719-e858-4ff0-9467-b8dbf9c0ee5b"}
            old_global["Name"] = "My global dance timing"
            for index, child in enumerate(legacy_home["Children"]):
                if child["SymbolName"].endswith("BlenderSourceClip"):
                    renamed[child["Id"]] = f"b62d1029-d8e8-40f4-8bd0-{index:012x}"
                    child["Name"] = f"My source {index}"
            for child in legacy_home["Children"]:
                child["Id"] = renamed.get(child["Id"], child["Id"])
            for edge in legacy_home["Connections"]:
                for field in ("SourceParentOrChildId", "TargetParentOrChildId"):
                    edge[field] = renamed.get(edge[field], edge[field])
            for item in legacy_ui["SymbolChildUis"]:
                item["ChildId"] = renamed.get(item["ChildId"], item["ChildId"])
            overlap_home = copy.deepcopy(legacy_home)
            overlap_ui = copy.deepcopy(legacy_ui)
            overlap_plan = json.loads(files[3].read_text())
            overlap_plan["clips"][0]["end"] = 20
            overlap_plan["clips"][1]["start"] = 20
            overlap_clips = [child for child in overlap_home["Children"]
                             if child["SymbolName"].endswith("BlenderSourceClip")]
            overlap_clips[0]["Outputs"][0]["OutputData"]["TimeClip"]["SourceRange"]["End"] = 20
            overlap_clips[1]["Outputs"][0]["OutputData"]["TimeClip"]["SourceRange"]["Start"] = 20
            self.assertTrue(_link_world_clips(overlap_home, overlap_ui,
                                              overlap_plan, graph["Id"]))
            overlap_sequences = {child["Id"] for child in overlap_home["Children"]
                                 if child["Name"].endswith(" / clips")}
            self.assertEqual(sum(edge["TargetParentOrChildId"] in overlap_sequences
                                 and edge["TargetSlotId"] == "36bf79ae-84ac-5691-b8cb-a65d2e055d1a"
                                 for edge in overlap_home["Connections"]), 3)
            self.assertTrue(_link_world_clips(legacy_home, legacy_ui,
                                              json.loads(files[3].read_text()), graph["Id"]))
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderWorldClipTime")
                                 for child in legacy_home["Children"]), 2)

            clips[1]["Outputs"][0]["OutputData"]["TimeClip"]["SourceRange"]["Start"] = 3
            # A user can insert a float operator between a world clip lane
            # and its animation. Resync must preserve that custom route.
            edited_edge = next(edge for edge in home["Connections"]
                               if edge["SourceParentOrChildId"] in routers
                               and edge["TargetSlotId"] == "ee2eaef9-6e5a-48b3-9df0-91b2f9ab7dc7")
            modifier_id = "ec06444d-b4e2-4561-a108-74d99cfc17e5"
            home["Children"].append({"Id": modifier_id, "SymbolId": modifier_id,
                                     "SymbolName": "User.FloatModifier", "Name": "My time modifier",
                                     "InputValues": [], "Outputs": []})
            home["Connections"].append({
                "SourceParentOrChildId": edited_edge["SourceParentOrChildId"],
                "SourceSlotId": edited_edge["SourceSlotId"],
                "TargetParentOrChildId": modifier_id,
                "TargetSlotId": "26d62e14-93cf-4704-a49d-b7f860689d58",
            })
            edited_edge["SourceParentOrChildId"] = modifier_id
            edited_edge["SourceSlotId"] = "cd0c8520-82dc-4389-82ae-7c4e3788cb0e"
            home_path.write_text(json.dumps(home, indent=2))
            edited_home = home_path.read_bytes()
            scene["Children"][0]["Name"] = "My persistent render edit"
            scene_path.write_text(json.dumps(scene, indent=2))
            edited_scene = scene_path.read_bytes()
            populate(project, files, root / "backups", root, build=False)
            self.assertEqual(home_path.read_bytes(), edited_home)
            self.assertEqual(scene_path.read_bytes(), edited_scene)
            self.assertTrue((project / "Symbols" / "PrismalLabs" / "BlenderExport"
                             / "Generated" / files[0].name).is_file())

            # Repair a home flattened by an older bridge, when a child reused
            # the archived scene symbol's ID in TiXL's global instance registry.
            legacy = json.loads(home_path.read_text())
            legacy_ui_path = project / "Symbols" / "DanceProject.t3ui"
            legacy_ui = json.loads(legacy_ui_path.read_text())
            old_scene_id = graph["Children"][0]["Id"]
            old_home_id = next(child["Id"] for child in legacy["Children"]
                               if child["Name"] == graph["Children"][0]["Name"])
            for child in legacy["Children"]:
                if child["Id"] == old_home_id:
                    child["Id"] = old_scene_id
            for edge in legacy["Connections"]:
                for field in ("SourceParentOrChildId", "TargetParentOrChildId"):
                    if edge[field] == old_home_id:
                        edge[field] = old_scene_id
            for item in legacy_ui["SymbolChildUis"]:
                if item["ChildId"] == old_home_id:
                    item["ChildId"] = old_scene_id
            home_path.write_text(json.dumps(legacy, indent=2))
            legacy_ui_path.write_text(json.dumps(legacy_ui, indent=2))
            populate(project, files, root / "backups", root, build=False)
            repaired = json.loads(home_path.read_text())
            self.assertFalse({child["Id"] for child in repaired["Children"]}
                             & {child["Id"] for child in scene["Children"]})
            self.assertEqual(len(repaired["Connections"]), len(legacy["Connections"]))

            # An existing flat graph from the previous bridge is upgraded in
            # place, including its user-edited TimeClips.
            without_preload = json.loads(home_path.read_text())
            without_preload_ui = json.loads(legacy_ui_path.read_text())
            removed_id = next(child["Id"] for child in without_preload["Children"]
                              if child["SymbolName"].endswith("BlenderWorldPreload"))
            without_preload["Children"] = [child for child in without_preload["Children"]
                                           if child["Id"] != removed_id]
            before = [edge for edge in without_preload["Connections"]
                      if edge["TargetParentOrChildId"] == removed_id]
            after = [edge for edge in without_preload["Connections"]
                     if edge["SourceParentOrChildId"] == removed_id]
            switch_edge = next(edge for edge in before
                               if edge["TargetSlotId"] == "8bf57a9c-25a2-4a41-a349-4a1769ff904b")
            lights_edge = after[0]
            without_preload["Connections"] = [edge for edge in without_preload["Connections"]
                                               if edge not in before + after]
            without_preload["Connections"].append({
                "SourceParentOrChildId": switch_edge["SourceParentOrChildId"],
                "SourceSlotId": switch_edge["SourceSlotId"],
                "TargetParentOrChildId": lights_edge["TargetParentOrChildId"],
                "TargetSlotId": lights_edge["TargetSlotId"],
            })
            without_preload_ui["SymbolChildUis"] = [item for item in without_preload_ui["SymbolChildUis"]
                                                     if item["ChildId"] != removed_id]
            home_path.write_text(json.dumps(without_preload, indent=2))
            legacy_ui_path.write_text(json.dumps(without_preload_ui, indent=2))
            populate(project, files, root / "backups", root, build=False)
            upgraded = json.loads(home_path.read_text())
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderWorldPreload")
                                 for child in upgraded["Children"]), 1)

            # Migrate an older project with a nested scene while retaining edited clips.
            output_id = next(edge["TargetSlotId"] for edge in graph["Connections"]
                             if edge["TargetParentOrChildId"] == "00000000-0000-0000-0000-000000000000")
            wrapper, wrapper_ui = _build_home(
                graph, json.loads(files[1].read_text()), json.loads(files[3].read_text()),
                home["Id"], "DanceProject", scene["Id"],
                "PrismalLabs.DanceProject.DanceProjectScene", graph["Inputs"][0]["Id"], output_id)
            wrapper_clip = next(child for child in wrapper["Children"]
                                if child["Name"] == "02 / Spin")
            wrapper_clip["Outputs"][0]["OutputData"]["TimeClip"]["SourceRange"]["Start"] = 4
            home_path.write_text(json.dumps(wrapper, indent=2))
            (project / "Symbols" / "DanceProject.t3ui").write_text(json.dumps(wrapper_ui, indent=2))
            populate(project, files, root / "backups", root, build=False)
            migrated = json.loads(home_path.read_text())
            self.assertFalse(any(child["SymbolId"] == scene["Id"] for child in migrated["Children"]))
            self.assertEqual(sum(child["SymbolName"].endswith("BlenderTextureSelect")
                                 for child in migrated["Children"]), 2)
            self.assertEqual(next(child for child in migrated["Children"]
                                  if child["Name"] == "02 / Spin")["Outputs"][0]
                             ["OutputData"]["TimeClip"]["SourceRange"]["Start"], 4)


if __name__ == "__main__":
    unittest.main()
