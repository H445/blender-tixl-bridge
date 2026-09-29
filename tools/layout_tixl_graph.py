"""Stage or apply a deterministic layout for a TiXL composition.

Only child positions in the .t3ui file are written. Apply to an existing home
only after confirming the loaded editor has no unsaved graph changes, then
restart TiXL through the configured debug bridge.
"""

import argparse
import copy
import json
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "blender_tixl_bridge" / "source"
sys.path.insert(0, str(SOURCE))
from blend_sync_project import _read_tixl_json  # noqa: E402
from connected_graph_layout import count_wire_crossings, layout_connected_graph  # noqa: E402


def arrange(graph_path: Path, ui_path: Path, output_path: Path,
            backup_path: Path | None = None) -> dict:
    graph_path = graph_path.resolve()
    ui_path = ui_path.resolve()
    output_path = output_path.resolve()
    graph = _read_tixl_json(graph_path)
    original = _read_tixl_json(ui_path)
    arranged = copy.deepcopy(original)
    before = count_wire_crossings(graph, original)
    metrics = layout_connected_graph(graph, arranged)
    if metrics['crossings'] > before:
        raise ValueError('Layout increases crossing wires; original UI kept')
    if output_path == ui_path:
        if backup_path is None:
            raise ValueError('Applying in place requires --backup outside Symbols')
        backup_path = backup_path.resolve()
        if (backup_path in (ui_path, output_path) or
                any(part.casefold() == 'symbols' for part in backup_path.parts)):
            raise ValueError('Keep the backup outside every TiXL Symbols directory')
        if backup_path.exists():
            raise ValueError('Backup already exists; choose a new recovery path')
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(ui_path.read_bytes())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(arranged, indent=2, ensure_ascii=False) + '\n'
    if output_path == ui_path:
        staged = output_path.with_suffix(output_path.suffix + '.tmp')
        staged.write_text(payload, encoding='utf-8')
        staged.replace(output_path)
    else:
        output_path.write_text(payload, encoding='utf-8')
    checked = _read_tixl_json(output_path)
    assert set(entry['ChildId'] for entry in checked['SymbolChildUis']) == {
        child['Id'] for child in graph['Children']}
    assert count_wire_crossings(graph, checked) == metrics['crossings']
    assert {k: v for k, v in checked.items() if k != 'SymbolChildUis'} == {
        k: v for k, v in original.items() if k != 'SymbolChildUis'}
    assert all({k: v for k, v in new.items() if k != 'Position'} ==
               {k: v for k, v in old.items() if k != 'Position'}
               for new, old in zip(checked['SymbolChildUis'],
                                   original['SymbolChildUis']))
    return {'input': str(ui_path), 'output': str(output_path),
            'crossingsBefore': before, 'crossingsAfter': metrics['crossings'],
            'children': metrics['children'],
            'connections': metrics['connections'],
            'columns': metrics['columns'], 'width': metrics['width']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', required=True, type=Path)
    parser.add_argument('--ui', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    print(json.dumps(arrange(args.graph, args.ui, args.output, args.backup),
                     indent=2))
