"""Read-only, bounded bridge diagnostics with immutable detailed evidence.

Blender actions remain owned by Blender MCP. This CLI uses the TiXL debug
client and reads committed cache artifacts. Explicit captures temporarily change
time/playback and restore them; default inspection does not mutate either app.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import struct
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / 'blender_tixl_bridge' if (ROOT / 'blender_tixl_bridge').is_dir() else ROOT
sys.path.insert(0, str(PACKAGE / 'source'))
from tixl_bridge import exchange
from cache_publication import active_root, MARKER
from cache_bindings import PATH_INPUTS

SCHEMA = 1
LOG_CAPACITY = 4096  # Matching protocol 1 DebugLogBuffer; gaps remain explicit.


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def file_digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe_json(value):
    # Keep malformed numeric evidence recoverable without emitting invalid JSON.
    if isinstance(value, float) and not math.isfinite(value):
        return {'nonFinite': str(value)}
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(safe_json(value), indent=2, allow_nan=False) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def compact(value, limit=160):
    if isinstance(value, str):
        return value if len(value) <= limit else {'type': 'string', 'prefix': value[:limit],
                                                 'length': len(value), 'sha256': digest(value)}
    if isinstance(value, (list, dict)):
        return {'type': type(value).__name__, 'count': len(value), 'sha256': digest(value),
                'details': 'receipt.json'}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Non-finite diagnostic value')
    return value


def context_key(context):
    return {key: context.get(key) for key in ('hasOpenProject', 'compositionSymbolId',
                                             'compositionPath', 'outputView', 'selectedChildren')}


def cache_evidence(cache):
    if cache is None:
        return {'status': 'not requested'}, None
    cache = Path(cache).resolve()
    root = active_root(cache)  # Verifies payload membership and every content hash.
    marker = read_json(root / MARKER)
    manifest = read_json(root / 'worlds/manifest.json')
    if not isinstance(manifest, dict) or manifest.get('generation') != root.name:
        raise ValueError('Manifest generation does not match verified commit')
    source = Path(manifest['source_blend'])
    if not source.is_file() or file_digest(source) != manifest['source_sha256']:
        raise ValueError('Authored source is missing or changed since this generation')
    identity = {'cache': str(cache), 'generation': root.name, 'markerSha256': file_digest(root / MARKER),
                'sourceSha256': manifest['source_sha256']}
    summary = {'status': 'verified', **identity, 'fileCount': len(marker['files']),
               'worldCount': len(manifest['worlds']),
               'worlds': [compact(world['world']) for world in manifest['worlds'][:12]],
               'worldsOmitted': max(0, len(manifest['worlds']) - 12),
               'manifest': str(root / 'worlds/manifest.json')}
    return summary, {'identity': identity, 'manifest': manifest, 'marker': marker}


def graph_summary(graph, context, node_ids, limit):
    children = graph.get('children')
    connections = graph.get('connections')
    if not isinstance(children, list) or not isinstance(connections, list):
        raise ValueError('Malformed graph response: children/connections must be arrays')
    index = {child['childId']: child for child in children}
    requested = list(dict.fromkeys(node_ids))
    if not requested:
        requested = [child['childId'] for child in context.get('selectedChildren', [])]
    if not requested and context.get('outputView', {}).get('childId'):
        requested = [context['outputView']['childId']]
    if not requested and children:
        requested = [sorted(index)[0]]
    missing_requested = [item for item in requested if item not in index]
    focus = set(requested)
    for connection in connections:
        source, target = connection.get('sourceParentOrChildId'), connection.get('targetParentOrChildId')
        if source in requested or target in requested:
            focus.update((source, target))
    ordered = list(dict.fromkeys([item for item in requested if item in index]
                                + sorted(item for item in focus if item in index)))
    chosen = ordered[:limit]
    rows = []
    for child_id in chosen:
        child = index[child_id]
        inputs = child.get('inputs', [])
        if not isinstance(inputs, list):
            raise ValueError('Malformed node input inventory')
        rows.append({'childId': child_id, 'symbolId': child.get('symbolId'),
                     'symbolName': compact(child.get('symbolName')), 'name': compact(child.get('name')),
                     'isDisabled': bool(child.get('isDisabled')), 'isBypassed': bool(child.get('isBypassed')),
                     'inputs': [{**{key: compact(item.get(key)) for key in ('id', 'name', 'isDefault')},
                                 'value': compact(item.get('value'))} for item in inputs[:12]],
                     'inputsOmitted': max(0, len(inputs) - 12)})
    edges = [edge for edge in connections if edge.get('sourceParentOrChildId') in chosen
             or edge.get('targetParentOrChildId') in chosen]
    unresolved = {name: graph.get(name, []) for name in ('missingChildren', 'missingConnections')}
    if any(not isinstance(value, list) for value in unresolved.values()):
        raise ValueError('Malformed unresolved-structure inventory')
    return {'symbolId': graph.get('symbolId'), 'symbolName': compact(graph.get('symbolName')),
            'childCount': len(children), 'connectionCount': len(connections),
            'requestedIds': [compact(item) for item in requested[:limit]], 'requestedIdsOmitted': max(0, len(requested) - limit),
            'requestedIdsNotFound': [compact(item) for item in missing_requested[:limit]],
            'requestedIdsNotFoundCount': len(missing_requested),
            'nodes': rows, 'nodesOmitted': max(0, len(ordered) - limit),
            'connections': edges[:24], 'connectionsOmitted': max(0, len(edges) - 24),
            'unresolved': {name: {'count': len(value), 'sample': [({**{key: compact(item) for key, item in list(row.items())[:8]},
                                            'fieldsOmitted': max(0, len(row) - 8)} if isinstance(row, dict) else compact(row)) for row in value[:12]],
                                'omitted': max(0, len(value) - 12)} for name, value in unresolved.items()},
            'sha256': digest(graph)}


def log_summary(entries, guard, limit, gap=False, reset=False):
    warnings = [entry for entry in guard if str(entry.get('level', '')).lower() in ('warning', 'warn', 'error')]
    errors = [entry for entry in warnings if str(entry.get('level', '')).lower() == 'error']
    newest = (list(reversed(errors)) + [entry for entry in reversed(warnings) if entry not in errors])[:limit]
    return {'newEntries': len(entries), 'retainedWarnings': len(warnings) - len(errors),
            'retainedErrors': len(errors), 'gap': gap, 'cursorReset': reset,
            'records': [{**{key: item.get(key) for key in ('seq', 'time', 'level', 'sourceId')},
                         'message': compact(item.get('message'), 240)} for item in newest],
            'recordsOmitted': max(0, len(warnings) - limit),
            'historyScope': 'Retained server history, not necessarily this task; older ring history is unavailable'}



def capture_output(request, context, times, folder):
    if not context.get('outputView', {}).get('isPinned'):
        raise ValueError('Capture requires an already pinned render output')
    original = context['time']
    captures, primary, restore_errors = [], None, []
    try:
        if original.get('isPlaying'):
            request('setPlayback', playing=False)
        for index, time_value in enumerate(times):
            request('setTime', timeInSecs=time_value)
            request('pumpFrames', count=3)
            path = folder / f'output_{index:03d}.png'
            metadata = request('screenshot', target='output', path=str(path))
            with path.open('rb') as stream:
                header = stream.read(24)
            if header[:8] != b'\x89PNG\r\n\x1a\n' or len(header) < 24:
                raise ValueError('Output capture is not a readable PNG')
            width, height = struct.unpack('>II', header[16:24])
            if not width or not height:
                raise ValueError('Output capture has empty dimensions')
            captures.append({'timeInSecs': time_value, 'path': str(path), 'sha256': file_digest(path),
                             'bytes': path.stat().st_size, 'width': width, 'height': height,
                             'apiEvidence': metadata})
    except BaseException as error:
        primary = error
    finally:
        for method, params in [('setPlayback', {'playing': original.get('isPlaying', False)}),
                               ('setPlayback', {'speed': original['playbackSpeed']}),
                               ('setTime', {'timeInSecs': original['timeInSecs']})]:
            try:
                request(method, **params)
            except BaseException as error:
                restore_errors.append(type(error).__name__ + ": " + str(error))
        try:
            restored = request('getContext').get('time', {})
            if (restored.get('isPlaying') != original.get('isPlaying')
                    or restored.get('playbackSpeed') != original.get('playbackSpeed')
                    or not math.isclose(restored.get('timeInSecs', math.inf), original['timeInSecs'],
                                        abs_tol=0.05 if original.get('isPlaying') else 1e-6, rel_tol=0)):
                restore_errors.append('Capture playback/time restoration readback failed')
        except BaseException as error:
            restore_errors.append(type(error).__name__ + ': ' + str(error))
    if primary is not None or restore_errors:
        raise RuntimeError('Capture failed: ' + (type(primary).__name__ + ": " + str(primary) if primary else 'state restoration')
                           + '; restore errors: ' + '; '.join(restore_errors))
    return captures


def bound_summary(summary, budget=16384):
    summary['summaryBudgetBytes'] = budget
    graph, logs = summary.get('graph', {}), summary.get('logs', {})
    groups = [(graph, 'nodes', 'nodesOmitted', 1 if graph.get('nodes') else 0), (graph, 'connections', 'connectionsOmitted', 0),
              (graph, 'requestedIds', 'requestedIdsOmitted', 0),
              (logs, 'records', 'recordsOmitted', 1 if logs.get('retainedErrors') else 0),
              (summary.get('cache', {}), 'worlds', 'worldsOmitted', 0),
              (summary.get('render', {}), 'captures', 'capturesOmitted', 1)]
    for node in graph.get('nodes', []):
        groups.append((node, 'inputs', 'inputsOmitted', 0))
    for value in graph.get('unresolved', {}).values():
        groups.append((value, 'sample', 'omitted', 1 if value.get('count') else 0))
    while len(json.dumps(summary, allow_nan=False).encode('utf-8')) > budget:
        candidates = [(len(json.dumps(group.get(key, []))), group, key, omitted)
                      for group, key, omitted, minimum in groups if len(group.get(key, [])) > minimum]
        if not candidates:
            raise ValueError('Diagnostic metadata exceeds the summary budget')
        _, group, key, omitted = max(candidates, key=lambda row: row[0])
        group[key].pop()
        group[omitted] = group.get(omitted, 0) + 1
    return summary


def collect_diagnostics(output, mode='inspect', port=9042, cache=None, node_ids=(),
                        node_limit=12, log_limit=12, full=False, caller=exchange, capture_times=()):
    if mode not in ('inspect', 'logs', 'cache') or not 1 <= node_limit <= 100 or not 1 <= log_limit <= 100:
        raise ValueError('Invalid diagnostic mode or summary limits')
    if len(capture_times) > 64 or any(not math.isfinite(value) for value in capture_times):
        raise ValueError('Capture requires at most 64 finite source times')
    if capture_times and mode != 'inspect':
        raise ValueError('Capture requires fresh graph inspection')
    output = Path(output).resolve()
    if cache is not None and output.is_relative_to(Path(cache).resolve() / 'generations'):
        raise ValueError('Evidence output must not modify export generations')
    if any((ancestor / MARKER).is_file() for ancestor in (output, *output.parents)):
        raise ValueError('Evidence output must not modify a committed generation')
    receipt_dir = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '_' + uuid.uuid4().hex[:12])
    receipt_dir.mkdir(parents=True)
    state_path = output / 'cursor.json'
    previous = read_json(state_path) or {}
    receipt = {'schema': SCHEMA, 'mode': mode, 'createdUtc': datetime.now(timezone.utc).isoformat(),
               'toolEvidence': {'helperSha256': file_digest(Path(__file__)),
                                'clientSha256': file_digest(PACKAGE / 'source/tixl_bridge.py')},
               'requests': [], 'cache': None, 'errors': [],
               'options': {'nodeIds': list(node_ids), 'nodeLimit': node_limit, 'logLimit': log_limit,
                           'captureTimes': list(capture_times)}}
    summary = {'schema': SCHEMA, 'mode': mode, 'ok': False,
               'evidence': str(receipt_dir / 'receipt.json'),
               'validation': 'Diagnostic evidence only; rendered output still requires visual verification'}

    def request(method, **params):
        row = {'method': method, 'params': params}
        receipt['requests'].append(row)
        try:
            wire = caller(method, port, **params)
            row['wire'] = wire
            envelope = wire['response']
            if not isinstance(envelope, dict) or not envelope.get('ok'):
                raise RuntimeError(json.dumps(envelope))
            response = envelope.get('result')
            if not isinstance(response, dict):
                raise ValueError('Expected an object result from ' + method)
            row['response'] = response
            digest(response)  # Reject non-finite numbers before a successful receipt.
            return response
        except Exception as error:
            row['error'] = str(error)
            raise

    try:
        generation, details = cache_evidence(cache)
        receipt['cache'] = details
        summary['cache'] = dict(generation)
        if mode == 'cache':
            if details is None:
                raise ValueError('Cache mode requires a committed cache directory')
            summary['ok'] = True
        else:
            version = request('getVersion') if mode == 'inspect' or not previous else previous.get('version', {})
            context = request('getContext')
            if not context.get('hasOpenProject'):
                raise ValueError('No TiXL project is open')
            base_identity = {'context': context_key(context), 'generation': (details or {}).get('identity'),
                             'port': port}
            same_identity = previous.get('schema') == SCHEMA and previous.get('identity') == base_identity
            cursor = previous.get('cursor') if same_identity and mode == 'logs' else None
            cursor = cursor if type(cursor) is int and cursor >= 0 else None
            if mode == 'inspect' and version.get('protocolVersion') != 1:
                raise ValueError('Unsupported protocol: unresolved-structure contract needs review')
            structure_before = request('getStructureVersion') if mode == 'inspect' else None
            graph = request('getGraphState', compositionId=context['compositionSymbolId'], includeDefaults=False) if mode == 'inspect' else None
            if graph is not None:
                if graph.get('symbolId') != context['compositionSymbolId']:
                    raise ValueError('Graph response belongs to another composition')
                summary['graph'] = graph_summary(graph, context, node_ids, node_limit)
                if details is not None:
                    generation_root = Path(details['identity']['cache']) / 'generations' / details['identity']['generation']
                    asset_paths = []
                    for child in graph['children']:
                        symbol = child.get('symbolName', '').split('.')[-1]
                        slots = PATH_INPUTS.get(symbol, set())
                        for item in child.get('inputs', []):
                            name = item.get('name', '')
                            if item.get('id') not in slots and name not in {'DataPath', 'GlbPath', 'FilePath', 'CameraDataPath', 'TimelineDataPath', 'WorldDirectory'}:
                                continue
                            if symbol not in PATH_INPUTS:
                                continue
                            value = item.get('value')
                            if not isinstance(value, str) or not value:
                                raise ValueError('Managed asset path is missing')
                            target = Path(value).resolve()
                            if not target.is_relative_to(generation_root.resolve()):
                                raise ValueError('Live asset path is outside the requested generation')
                            relative = target.relative_to(generation_root.resolve()).as_posix()
                            if symbol == 'BlenderExportLights':
                                valid = relative == 'worlds' and target.is_dir() and any(key.endswith('_manifest.json') for key in details['marker']['files'])
                            else:
                                valid = target.is_file() and relative in details['marker']['files']
                                if symbol == 'LoadGltfScene' or name == 'GlbPath' or item.get('id') == '3a4c36f9-e8c1-4ab7-b370-0f548b054933':
                                    valid = valid and relative.startswith('worlds/') and relative.endswith('.glb')
                                elif symbol == 'BlenderAnimationScene':
                                    valid = valid and relative.startswith('worlds/') and relative.endswith('_animation.bin')
                                elif name == 'CameraDataPath' or item.get('id') == '0713a026-3b7b-5ddf-ac49-e585d8248fa6':
                                    valid = valid and relative == 'camera_60hz.bin'
                                else:
                                    valid = valid and relative == 'camera_timeline.json'
                            if not valid:
                                raise ValueError('Live asset path is not a committed asset of the expected kind')
                            asset_paths.append(relative)
                    if not asset_paths:
                        raise ValueError('Live asset paths do not establish alignment with the requested generation')
                    receipt['liveAssetPaths'] = sorted(set(asset_paths))
                    summary['cache']['liveAssetPathsVerified'] = len(asset_paths)
            else:
                summary['graph'] = {'status': 'not inspected; previous graph evidence is historical'}
            if capture_times:
                if any(graph.get(name) for name in ('missingChildren', 'missingConnections')):
                    raise ValueError('Refusing render capture with unresolved graph structure')
                captures = capture_output(request, context, capture_times, receipt_dir)
                receipt['renderCaptures'] = captures
                summary['render'] = {'status': 'needs visual review; file/size checks are not render verification',
                                     'captures': [{key: capture[key] for key in ('timeInSecs', 'path', 'sha256', 'width', 'height')} for capture in captures[:12]],
                                     'capturesOmitted': max(0, len(captures) - 12)}
            logs = request('getLogTail', sinceSeq=-1 if cursor is None else cursor - 1,
                           minLevel='debug', maxCount=LOG_CAPACITY)
            entries = logs.get('entries')
            if not isinstance(entries, list):
                raise ValueError('Malformed log entries')
            reset = cursor is None
            gap = logs.get('oldestAvailableSeq', 0) > 0 if cursor is None else False
            if cursor is not None:
                anchor = next((item for item in entries if item.get('seq') == cursor), None)
                gap = cursor < logs.get('oldestAvailableSeq', 0)
                if anchor is None or digest(anchor) != previous.get('anchorSha256'):
                    logs = request('getLogTail', sinceSeq=-1, minLevel='debug', maxCount=LOG_CAPACITY)
                    entries = logs['entries']
                    gap = gap or logs.get('oldestAvailableSeq', 0) > 0
                    reset = True
                else:
                    entries = [item for item in entries if item.get('seq', -1) > cursor]
                # There is no session ID in protocol 1. Re-read all retained
                # warnings/errors so a restarted sequence cannot hide failures.
                guard_tail = request('getLogTail', sinceSeq=-1, minLevel='warning', maxCount=LOG_CAPACITY)
                guard = guard_tail['entries']
                gap = gap or guard_tail.get('oldestAvailableSeq', 0) > (0 if reset else cursor)
            else:
                guard = entries
            summary['logs'] = log_summary(entries, guard, log_limit, gap, reset)
            summary['logs']['latestSeq'] = logs.get('latestSeq')
            summary['logs']['oldestAvailableSeq'] = logs.get('oldestAvailableSeq')
            structure_after = request('getStructureVersion') if mode == 'inspect' else None
            after = request('getContext')
            if mode == 'inspect':
                if (type(structure_before.get('symbolStructureVersion')) is not int
                        or type(structure_after.get('symbolStructureVersion')) is not int
                        or structure_before != structure_after):
                    raise ValueError('Symbol structure changed during diagnostics; retry')
                contexts = [row['wire']['response'] for row in receipt['requests'] if row['method'] == 'getContext']
                before_ui, after_ui = contexts[0].get('structureVersion'), contexts[-1].get('structureVersion')
                if type(before_ui) is not int or type(after_ui) is not int or before_ui != after_ui:
                    raise ValueError('Graph UI structure changed or is unavailable; retry')
                summary['consistency'] = {'symbolStructure': structure_after, 'uiStructureVersion': after_ui,
                                          'scope': 'Live in-memory snapshot; structural disk edits still require saved-work restart'}
            if context_key(after) != context_key(context):
                raise ValueError('Project/selection/output changed during diagnostics; retry')
            if capture_times:
                original_time, restored_time = context['time'], after.get('time', {})
                if (restored_time.get('isPlaying') != original_time.get('isPlaying')
                        or restored_time.get('playbackSpeed') != original_time.get('playbackSpeed')
                        or not math.isclose(restored_time.get('timeInSecs', math.inf), original_time['timeInSecs'], abs_tol=0.05 if original_time.get('isPlaying') else 1e-6, rel_tol=0)):
                    raise ValueError('Capture playback/time restoration readback failed')
            generation_after, _ = cache_evidence(cache)
            if generation_after != generation:
                raise ValueError('Committed generation changed during diagnostics; retry')
            summary['context'] = {'compositionSymbolId': context.get('compositionSymbolId'),
                                  'compositionName': compact(context.get('compositionName')),
                                  'outputView': {key: compact(context.get('outputView', {}).get(key)) for key in ('childId', 'isPinned', 'symbolName', 'path')},
                                  'timeBefore': {key: compact(context.get('time', {}).get(key)) for key in ('timeInSecs', 'timeInBars', 'playbackSpeed', 'isPlaying', 'bpm')},
                                  'timeAfter': {key: compact(after.get('time', {}).get(key)) for key in ('timeInSecs', 'timeInBars', 'playbackSpeed', 'isPlaying', 'bpm')}}
            summary['version'] = {key: compact(version.get(key), 80) for key in ('editorVersion', 'protocolVersion')}
            summary['version']['source'] = 'fresh' if mode == 'inspect' or not previous else 'previous inspect; not reread in log follow'
            summary['logs']['cursorContinuity'] = 'reset' if reset else 'inferred from anchor; server session ID unavailable'
            unresolved = graph is not None and any(graph.get(name) for name in ('missingChildren', 'missingConnections'))
            bad_target = graph is not None and summary['graph']['requestedIdsNotFoundCount'] > 0
            summary['ok'] = not (unresolved or bad_target or summary['logs']['retainedErrors'] or gap)
            all_entries = logs['entries']
            anchor = max(all_entries, key=lambda item: item.get('seq', -1), default=None)
            receipt['identity'] = base_identity
            receipt['observedContext'] = context
            receipt['version'] = version
            if anchor is not None:
                receipt['nextCursor'] = {'schema': SCHEMA, 'identity': base_identity, 'version': version,
                                         'cursor': anchor['seq'], 'anchorSha256': digest(anchor)}
    except Exception as error:
        receipt['errors'].append(str(error))
        summary['errors'] = [compact(str(error), 300)]
    summary['callCount'] = len(receipt['requests'])
    try:
        summary = bound_summary(summary)
    except ValueError as error:
        receipt['errors'].append(str(error))
        summary = {'schema': SCHEMA, 'mode': mode, 'ok': False, 'evidence': str(receipt_dir / 'receipt.json'),
                   'errors': [str(error)], 'validation': 'Summary unavailable; inspect preserved raw evidence',
                   'callCount': len(receipt['requests']), 'summaryBudgetBytes': 16384,
                   'retainedErrors': summary.get('logs', {}).get('retainedErrors'),
                   'unresolvedCounts': {key: value['count'] for key, value in summary.get('graph', {}).get('unresolved', {}).items()}}
        if len(json.dumps(summary).encode('utf-8')) > 16384:
            summary['evidence'] = 'receipt.json in the requested output run directory'
    receipt['summary'] = summary
    write_json(receipt_dir / 'receipt.json', receipt)
    # Persist cursors only after detailed evidence is durably published.
    if 'nextCursor' in receipt and not receipt['errors']:
        write_json(state_path, receipt['nextCursor'])
    if full:
        summary = {**summary, 'fullEvidence': receipt}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('inspect', 'logs', 'cache'), default='inspect')
    parser.add_argument('--output', type=Path, required=True, help='Private evidence/cursor directory')
    parser.add_argument('--port', type=int, default=9042)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--node', action='append', default=[])
    parser.add_argument('--node-limit', type=int, default=12)
    parser.add_argument('--log-limit', type=int, default=12)
    parser.add_argument('--capture-time', type=float, action='append', default=[],
                        help='Explicit output PNG capture at a source time; restores playback/time')
    parser.add_argument('--full', action='store_true', help='Explicitly print all captured detail')
    args = parser.parse_args()
    try:
        result = collect_diagnostics(args.output, args.mode, args.port, args.cache, args.node,
                                     args.node_limit, args.log_limit, args.full, capture_times=args.capture_time)
    except Exception as error:
        result = {'schema': SCHEMA, 'ok': False, 'errors': [compact(str(error), 300)],
                  'evidence': None, 'validation': 'Not completed'}
    print(json.dumps(result, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
