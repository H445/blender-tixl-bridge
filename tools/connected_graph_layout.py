"""Deterministic position-only layout for acyclic TiXL graphs."""

import re
from collections import defaultdict, deque


def count_wire_crossings(graph: dict, ui: dict) -> int:
    """Count strict center-line intersections, excluding shared endpoints."""
    positions = {entry['ChildId']: (entry['Position']['X'], entry['Position']['Y'])
                 for entry in ui['SymbolChildUis']}
    edges = [(edge['SourceParentOrChildId'], edge['TargetParentOrChildId'])
             for edge in graph['Connections']]

    def side(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

    crossings = 0
    for index, (source, target) in enumerate(edges):
        a, b = positions[source], positions[target]
        for other_source, other_target in edges[index+1:]:
            if source in (other_source, other_target) or target in (
                    other_source, other_target):
                continue
            c, d = positions[other_source], positions[other_target]
            if side(a, b, c)*side(a, b, d) < 0 and side(c, d, a)*side(c, d, b) < 0:
                crossings += 1
    return crossings


def layout_connected_graph(graph: dict, ui: dict, *, column=420, lane=900,
                           row=300, control_lane=0) -> dict:
    """Arrange any acyclic TiXL composition by its actual data flow.

    Only ``SymbolChildUis[*].Position`` changes. A longest-path backbone runs
    left to right; other operators move as late as their first consumer allows,
    keeping branches beside their use rather than beside a distant time source.
    Semantic name prefixes keep related side inputs in stable, separate lanes.
    Return layout metrics so agents can verify that no node or wire was lost.
    """
    children = {child['Id']: child for child in graph['Children']}
    entries = {entry['ChildId']: entry for entry in ui['SymbolChildUis']}
    if (len(children) != len(graph['Children']) or
            len(entries) != len(ui['SymbolChildUis']) or
            set(children) != set(entries)):
        raise ValueError('Graph and UI child IDs differ; preserve the original layout')
    parents, successors = defaultdict(set), defaultdict(set)
    for edge in graph['Connections']:
        source = edge['SourceParentOrChildId']
        target = edge['TargetParentOrChildId']
        if source not in children or target not in children:
            raise ValueError('Graph has a connection outside its children')
        if source != target:
            successors[source].add(target)
            parents[target].add(source)
    indegree = {child_id: len(parents[child_id]) for child_id in children}
    ready = deque(sorted((child_id for child_id in children if not indegree[child_id]),
                         key=lambda child_id: children[child_id]['Name']))
    order = []
    while ready:
        source = ready.popleft()
        order.append(source)
        for target in sorted(successors[source],
                             key=lambda child_id: children[child_id]['Name']):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
    if len(order) != len(children):
        raise ValueError('Cyclic graph requires a reviewed layout; no UI changed')

    earliest = {child_id: 0 for child_id in children}
    for source in order:
        for target in successors[source]:
            earliest[target] = max(earliest[target], earliest[source]+1)
    depth = max(earliest.values(), default=0)
    latest = {child_id: depth for child_id in children}
    for source in reversed(order):
        if successors[source]:
            latest[source] = min(latest[target]-1 for target in successors[source])
        latest[source] = max(earliest[source], latest[source])

    def family(child_id):
        name = children[child_id]['Name']
        if re.match(r'^\d\d\s*/', name) or 'clip' in name.lower():
            return 'Timeline'
        prefix = re.split(r'\s+[|/]\s+', name, maxsplit=1)[0]
        if prefix in ('Main', 'Blender', 'Output', 'Render', 'Environment',
                      'Resolution', 'Active Blender world', 'Tone mapping'):
            return 'Core'
        return prefix.split()[0]

    groups = defaultdict(list)
    for child_id in children:
        if earliest[child_id] != latest[child_id]:
            groups[family(child_id)].append(child_id)
    group_order = sorted(groups,
                         key=lambda name: (min(latest[child_id]
                                               for child_id in groups[name]), name))
    lane_numbers = {}
    for index, name in enumerate(group_order):
        lane_numbers[name] = (-1 if index % 2 == 0 else 1) * (index//2+1)

    columns = defaultdict(list)
    for child_id in children:
        columns[latest[child_id]].append(child_id)
    side_columns = defaultdict(dict)
    for layer, members in columns.items():
        critical = sorted((child_id for child_id in members
                           if earliest[child_id] == latest[child_id]),
                          key=lambda child_id: children[child_id]['Name'])
        for index, child_id in enumerate(critical):
            x = round(layer*column/140)*140
            # An explicit control_lane can lift source/timing nodes when that
            # improves a particular graph; zero keeps the shortest crossings.
            baseline = control_lane*lane if layer <= 3 else 0
            y = round((baseline+(index-(len(critical)-1)/2)*row)/35)*35
            entries[child_id]['Position'] = {'X': x, 'Y': y}
        side = defaultdict(list)
        for child_id in members:
            if child_id not in critical:
                side[family(child_id)].append(child_id)
        for name, group_members in side.items():
            # Sort by first downstream use, then name, so added operators do
            # not reorder unrelated branches when a graph grows.
            group_members.sort(key=lambda child_id: (
                min((latest[target] for target in successors[child_id]),
                    default=depth), children[child_id]['Name']))
            side_columns[layer][name] = group_members

    def place_side():
        for layer, groups_at_layer in side_columns.items():
            for name, group_members in groups_at_layer.items():
                for index, child_id in enumerate(group_members):
                    x = round(layer*column/140)*140
                    center = lane_numbers[name]*lane
                    y = round((center+(index-(len(group_members)-1)/2)*row)/35)*35
                    entries[child_id]['Position'] = {'X': x, 'Y': y}

    place_side()
    crossings = count_wire_crossings(graph, ui)
    # Adjacent semantic lanes can trade places without changing any node's
    # horizontal flow. Greedily keep swaps that reduce crossing wires.
    for _ in range(len(group_order)):
        best = None
        for index, left in enumerate(group_order):
            for right in group_order[index+1:]:
                lane_numbers[left], lane_numbers[right] = (
                    lane_numbers[right], lane_numbers[left])
                place_side()
                score = count_wire_crossings(graph, ui)
                if score < crossings and (best is None or score < best[0]):
                    best = (score, left, right)
                lane_numbers[left], lane_numbers[right] = (
                    lane_numbers[right], lane_numbers[left])
        place_side()
        if best is None:
            break
        crossings, left, right = best
        lane_numbers[left], lane_numbers[right] = (
            lane_numbers[right], lane_numbers[left])
        place_side()
    return {'children': len(children), 'connections': len(graph['Connections']),
            'columns': depth+1, 'lanes': len(group_order),
            'crossings': crossings,
            'width': max((entry['Position']['X'] for entry in entries.values()),
                         default=0)}
