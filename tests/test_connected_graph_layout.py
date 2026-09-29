"""Connection-driven layout keeps graph behavior and works as branches grow."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / 'tools'))
from connected_graph_layout import count_wire_crossings, layout_connected_graph


def graph_with_branches(branches):
    names = ['Source', 'Clock'] + [f'Effect {i} | control' for i in range(branches)]
    names += ['Scene', 'Render', 'Output']
    children = [{'Id': str(i), 'Name': name} for i, name in enumerate(names)]
    pairs = [(0, 1), (1, branches+2), (branches+2, branches+3),
             (branches+3, branches+4)]
    pairs += [(1, i+2) for i in range(branches)]
    pairs += [(i+2, branches+2) for i in range(branches)]
    graph = {'Children': children, 'Connections': [
        {'SourceParentOrChildId': str(a), 'TargetParentOrChildId': str(b)}
        for a, b in pairs]}
    ui = {'Description': 'keep this', 'SymbolChildUis': [
        {'ChildId': str(i), 'Position': {'X': 0, 'Y': 0}, 'Style': 'saved'}
        for i in range(len(names))]}
    return graph, ui


class ConnectedGraphLayoutTest(unittest.TestCase):
    def test_dynamic_branches_preserve_topology_and_unique_positions(self):
        for branches in (0, 1, 4, 12):
            with self.subTest(branches=branches):
                graph, ui = graph_with_branches(branches)
                original_graph, original_ui = copy.deepcopy(graph), copy.deepcopy(ui)
                summary = layout_connected_graph(graph, ui)
                self.assertEqual(graph, original_graph)
                self.assertEqual(ui['Description'], original_ui['Description'])
                self.assertEqual(summary['children'], len(graph['Children']))
                self.assertEqual(summary['connections'], len(graph['Connections']))
                self.assertEqual(len({(row['Position']['X'], row['Position']['Y'])
                                      for row in ui['SymbolChildUis']}),
                                 len(graph['Children']))
                self.assertTrue(all(row['Style'] == 'saved'
                                    for row in ui['SymbolChildUis']))
                positions = {row['ChildId']: row['Position']
                             for row in ui['SymbolChildUis']}
                self.assertTrue(all(positions[edge['SourceParentOrChildId']]['X'] <
                                    positions[edge['TargetParentOrChildId']]['X']
                                    for edge in graph['Connections']))
                self.assertEqual(summary['crossings'],
                                 count_wire_crossings(graph, ui))
                repeated = copy.deepcopy(original_ui)
                self.assertEqual(layout_connected_graph(graph, repeated), summary)
                self.assertEqual(repeated, ui)

    def test_cycle_fails_without_mutating_ui(self):
        graph, ui = graph_with_branches(2)
        graph['Connections'].append({'SourceParentOrChildId': '5',
                                     'TargetParentOrChildId': '2'})
        original = copy.deepcopy(ui)
        with self.assertRaisesRegex(ValueError, 'Cyclic graph'):
            layout_connected_graph(graph, ui)
        self.assertEqual(ui, original)


if __name__ == '__main__':
    unittest.main()
