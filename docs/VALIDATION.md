# Validation and performance measurement

Run the isolated Python regression suite from the repository root:

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

The reusable `unit-tests.yml` workflow runs this suite on Windows and Ubuntu for pull requests and branch pushes. It also installs the .NET 8 SDK and runs the production-source GLB reader and animation-cache regressions. `release.yml` depends on that workflow; a failing matrix job prevents ZIP building and release publication. Live Blender and TiXL checks are separate because they need local application installs and a GPU.

With the .NET 8 SDK available, run the C# regressions locally:

```powershell
python tests/glb_reader_validation.py --require-single-parse --iterations 40
python tests/animation_cache_validation.py
```

These scripts compile the actual private reader, track cache, runtime statistics,
and morph binding source in temporary projects. Small resource doubles replace
GPU dependencies for ownership checks. The fixtures exercise interleaved and
sparse morph data, material defaults, primitive centers, same-path reloads,
malformed atomic loads, cache identity and eviction, and both buffer disposal
orders. They require no third-party packages and fail if compilation or an
assertion fails.

## Structured sync measurements

Every sync returns a `metrics` JSON path under its cache's `sync_metrics/` directory. Reports share a run ID across queue, discovery, host sync, and Blender worker lanes. Each lane writes its own file. Completed worker files are listed in the host report; an asynchronous discovery file can arrive later. A skipped discovery reports `resultStatus: skipped`, rather than claiming a probe completed.

Reports record elapsed time, process ID, observed process launches, hashed bytes, committed cache bytes, process memory, and phase aggregates. Phases cover queue and lock wait, discovery, hashing, Blender startup, geometry export, animation and camera baking, validation, publication, graph generation, build, activation, and first evaluation when those operations occur. Startup is measured from the parent's launch timestamp to entry in the Blender worker. Phases can nest; their totals must not be added to derive overall wall time. Windows memory comes from `GetProcessMemoryInfo`; Unix reports process peak RSS. These are process-lifetime peaks, not allocation deltas.

Failed syncs preserve their report, attach its path as `exception.metrics_path`, and print a `SYNC_METRICS_REPORT` record. Reports include a bounded error message. Failure to write measurement files does not replace the export's result or exception.

## Repeatable local benchmarks

Launch `tests/blender_sync_benchmark.py` through Blender MCP in a disposable background Blender process with `--factory-startup`. It creates private fixtures and caches under `examples/.tixl_cache/benchmarks/` and leaves the interactive scene untouched. Its workloads cover a static cube's first/unchanged/edited sync, a 600-frame keyed timeline, three contiguous worlds, eight animated morph keys, and five rapid saved revisions submitted to the shared queue with actual CLI children. It waits for the first export to start before later saves, verifies at most one active and two total CLI children, and checks the final committed source matches the latest save. Process counts come from launch instrumentation, including failed requests.

This export benchmark uses `--no-install` and locally bypasses the editor transport wait. Installation and live rendering are excluded from its timings. The report includes fixture definitions, runtime versions, wall times, cache bytes, memory, and links to phase reports. Keep the complete ignored run folder when comparing results or diagnosing a regression.

With the bundled `BlendShapeExample` open in TiXL and its debug server enabled, run:

```powershell
python tests/tixl_runtime_benchmark.py --samples 120
```

The debug client verifies and clones the example payload, temporarily binds its data paths to one immutable generation, samples the full source timeline, checks that holding a frame stops uploads, and restores the graph, playhead, playback, selection, and output pin. It records fresh-path load wall time, bridge scene initialization time, editor-frame and debug-round-trip percentiles, managed/GPU memory, output resolution, and a screenshot.

`BlenderAnimationScene` exposes per-frame and cumulative scene-load, morph-upload, material-upload, and byte counts through TiXL's render statistics. Upload bytes cover this operator's vertex and material buffers; they exclude native glTF texture loading and other operators. Counters are bounded at the render-stat interface's maximum integer. The benchmark rejects saturated, negative, or decreasing cumulative counters and checks per-frame uploads while holding the source frame. Frame intervals come from the editor's debug metrics and include RPC pacing; they are separate from round-trip time and are not GPU timestamps.

## Initial baseline and targets

The [initial measured baseline](benchmarks/baseline-2026-09-27.json) records Blender 5.2.2 LTS and TiXL 4.3.0.2 on a Ryzen 7 5800X with a GTX 1660 Ti and about 128 GB RAM. One local run measured unchanged sync at 1.01 s and rebuild workloads at 6.02–6.19 s. Five rapid CLI requests committed the final saved source without a recovery request. At 3840×2160, 120 editor-frame samples gave p50 16.67 ms, p95 17.06 ms, and p99 17.22 ms. The bridge uploaded 37.3 MB across 71 morph updates; holding a source frame uploaded zero additional bytes.

Initial advisory limits are 1.3 s for unchanged sync, 8 s for these rebuild fixtures, and 20.5 ms for editor-frame p95 at the recorded resolution. They allow roughly 20–30% above the observed local values. The exact correctness targets are zero uploads on an unchanged source frame and a rapid-save cache matching the final source. The 60 Hz frame budget remains 16.67 ms; this baseline does not establish that every frame meets it.

Use the same fixture, output resolution, hardware, versions, and background workload when comparing runs. Repeat at least three times before treating a timing threshold breach as a regression. These initial timing limits are advisory, separate from the release-blocking unit tests, and should be tightened from further measurements.

The [save-during-export queue run](benchmarks/rapid-save-2026-09-27.json) submitted five saved revisions, launched two CLI children with a peak of one active child, and coalesced three intermediate requests. The first export was rejected after its source changed; the pending final request completed successfully. This differs from the initial burst baseline, which submitted all revisions before export startup.

The [capability discovery measurements](benchmarks/capability-discovery-2026-09-27.json) used the official add-on trigger. A forced complete refresh took 2.41 s; a reuse-window trigger took 0.023 s, excluding Python startup, with no file hashes, live probes, or report writes. Two unavailable-endpoint triggers both probed again and preserved the prior complete verification time. The normal endpoint and complete evidence were restored afterward.

The [operator hashing comparison](benchmarks/operator-hashing-2026-09-27.json) used identical private inputs with one mismatched C# file. Hashed bytes fell from 462,466 to 327,143 (about 29%); installation wrote only that file and preserved other destination timestamps. Builds, editor launch, and transport were bypassed, so these timings do not represent a full sync. Authored-source and export-contract validation still rehash their inputs.


### Generated-storage retention (2026-09-27)

[Portable retention evidence](benchmarks/retention-2026-09-27.json) records five actual forced exports in a disposable Blender 5.2.2 LTS process and a real missing-camera export failure. The fixture uses a private cache and fake TiXL scaffold which are never loaded into the editor; closed-editor cleanup eligibility is simulated only in that runner. Export times were 6.20–6.84 seconds, without a claim of a full-sync speedup. Three cleanup passes held two verified generations at 68,055 bytes and backup storage at 50,293 bytes: one owned backup plus an unmarked legacy backup. The failed stage, useful 2,118-byte export log, and parent/worker metrics remained available. Edited Home TimeClips, a custom Home field, and an independent user graph remained intact.

The installed add-on was verified against all 56 source package files and the ZIP was rebuilt. An installed-queue check submitted five requests to real Python children. It preserved active ownership and normalized the final pending log path through disable/enable; only two children launched and completed. The failed child emitted 200,017 bytes; its retained 907-byte log preserved HEAD and FINAL_FAILURE under a 1,024-byte budget, with 199,185 omitted bytes explicitly recorded. The latest completed log and queue outcome linked to FINAL_SUCCESS; the timer stopped after drain. This checks logging and queue lifecycle, not scene-export or GPU performance.

All 138 unit tests passed locally, including malformed recovery evidence, graph-directory reparse detection, interrupted nested process ownership, truncated completion markers, explicit-install recovery, and retained-queue metadata migration. TiXL 4.3.0.2's full 56-child graph and context matched before and after the checks. The output screenshot was visually inspected and still showed the paused blue cube. Raw fixture, queue, state, and image paths are recorded in the portable evidence; generated artifacts stay ignored.

### GLB loading and shared memory (2026-09-27)

[Portable GLB loading evidence](benchmarks/glb-loading-2026-09-27.json) compares
the legacy three-reader implementation with one shared parse. After five warmup
runs and 40 measured iterations of the numeric fixture, reads and JSON parses
fell from three to one. Median per-thread load allocation fell from 27,808 to
11,552 bytes; fixture elapsed-time median fell from 0.540 to 0.230 milliseconds.
These are synthetic reader measurements, not full-scene or rendering timings.
All numeric projections and same-path reload results matched exactly.

Three live paused example baselines measured a median 29,544 microseconds across
12 bridge scene initializations. Eight subsequent distinct-generation loads
measured a median 27,013 microseconds. Each initialization opened and parsed its
GLB once. Every run restored the complete graph and context, rendered a PNG
byte-identical to the baseline, and uploaded zero bytes on held source frames.
The existing example exercises opaque rendering; transparent material factors
and centers are also covered by the numeric fixture.

A separate private cube fixture set glTF BLEND alpha and sampled material alpha
to 0.35. Both the native loader and animation operator used that fixture. A
temporary alpha-blended draw node rendered `TransparentResult` at source times
0 and 3.5 seconds, showing the cube and its deformed rounded shape. Baseline and
optimized PNG bytes matched exactly at both times, with zero RGB error.
Alpha-zero control captures confirmed the transparent path contributed
2,572,421 and 1,336,626 visible pixels. Both phases preserved existing graph
edges and restored the complete graph, context, selection, and graph view.
The screenshots were visually inspected. The repeatable
`tests/transparent_render_equivalence.py` helper requires Pillow locally;
its offline route/fixture regressions use only the standard library.

The shared track cache reached 16 entries and plateaued at 587,160 accounted
bytes in the live fixture. Independent regressions exercised 48 generations,
the 64 MiB byte limit, oversized bypass, and gauge ownership transfer. This
accounting excludes tracks retained by live scenes and the whole editor heap.
Whole-editor managed memory continued to cycle with garbage collection.

Repeated loads exposed an original vertex buffer hidden by the morph replacement
wrapper when native scene disposal ran first. After correcting that ownership
case, debug-reported GPU usage stayed at 666.5 MiB across all eight resyncs;
the preceding run had risen from 672.9 to 698.4 MiB. Ownership regressions cover
both disposal orders and shared index/chunk resources. The operator compiled
against the installed TiXL dependencies, all 56 installed package files were
verified, and the add-on ZIP was rebuilt.

All 142 Python tests and both production-source C# harnesses passed locally.

To repeat the paused-load check, first retain a successful pre-change
`tixl_runtime_benchmark.py` run folder, then run:

```powershell
python tests/tixl_glb_loading_validation.py --baseline path/to/baseline --repetitions 8
```

It clones private data generations and restores each run before proceeding.
PNG byte equality is deliberately strict for this fixed example and environment;
use the same versions, resolution, hardware, and source data when comparing.

## Animation baking measurements (2026-09-27)

The measured exporter bottleneck was per-record seeking: a disposable Blender
scene with 100 animated objects and 600 shared output frames issued 60,000
matrix seeks. Bounded contiguous batches reduced that count to 100, while the
binary, metadata, and channel files remained byte-identical. The exploratory
profile decreased from 1.118 to 0.867 seconds; profiler overhead is included.

Five unprofiled complete bakes, including cache preparation, file closure, and
channel JSON output, measured medians of 0.927 seconds before and 0.612 seconds
after batching, about 34% lower for this workload. The baseline group ran before
the optimized group in one disposable Blender process. These are exporter
measurements; they do not establish faster complete syncs or playback. See the
portable [measurement report](benchmarks/animation-baking-2026-09-27.json).

A separate fixture started at source frame 11 with a 24 fps source and retained
60 Hz output sampling. Its three overlapping/disjoint world windows exercised
parented and static transforms, morphs, visibility, static/dynamic opaque and
transparent PBR/emission channels, and animated lights. All three worlds matched
the previous exporter byte for byte, and both versions set the shared scene
frame exactly 61 times. Fresh bakes of all four bundled-example worlds also
matched byte for byte and retained the existing GLB export names.

The live TiXL comparison used a complete private payload for each phase and
updated native GLB loaders last, after animation paths. This avoids reinitializing
from mutable dispatch counts between individual debug requests. Twelve captures
covered the cube, a deformed morph, and both sides of cuts at 4, 8, and 12 seconds.
Every baseline/optimized PNG matched exactly at 3840×2160. Unsaturated scene-load,
GLB-read, and JSON-parse counters stayed constant during source-time steps;
held-frame uploads were zero. Graph, timeline, selection, and view were restored,
then the original native scenes were refreshed with their restored paths.
The original project subsequently rendered all four worlds at 0, 4, 8, and
12 seconds with PNG bytes identical to the fresh baseline captures.

A private BLEND fixture also compared freshly baked cube and deformed-morph
data at 0 and 3.5 seconds. Material-channel alpha was set to 0.35 identically
in both fixtures. PNG bytes matched exactly with zero RGB error; alpha-zero
control captures proved a visible transparent-path contribution. Representative
opaque and transparent images were visually inspected.

The writer keeps the existing version 1 binary layout and uses an 8 MiB total
matrix-payload budget, at most 1,024 samples per batch, with direct writes when
only one sample fits. Object/allocator overhead is outside that payload budget.
Cache fingerprints include the writer module. Failure checks cover sampling,
buffer flush, writer construction, and stream-close errors; every stream receives
a close attempt and the original failure remains primary. All 162 Python tests
passed locally. The updated add-on verified 57 installed package files, preserved
the foreground Blender scene, and rebuilt its ZIP.

To repeat the Blender comparison, retain the previous exporter source (the
`a841ccd` revision is the baseline for these measurements). Launch
`tests/blender_animation_bake_validation.py` in a disposable Blender background
process through Blender MCP, passing arguments after Blender's `--` separator:

```text
--baseline path/to/previous/tixl_animation_export.py --example examples/BlendShapeExample.blend
```

The helper reports its private output folder. With the bundled example already
open and paused, use its `example_baseline` and `example_current` folders:

```powershell
python tests/tixl_animation_bake_validation.py --baseline path/to/example_baseline --optimized path/to/example_current --output path/to/new/private/render_folder
```

The live helper requires Pillow locally. Its offline fixture, counter, and
restoration tests use only the standard library and run in the normal CI suite.

## Documentation reading measurement

The [fixed-task report](benchmarks/documentation-reading-2026-09-27.json) compares
the previous required documents at `f46904892e8aba2d85e1920d251bbe859f0ba30c`
with the task router and generated capability summary. It counts full Markdown
bodies with line endings normalized to LF, using pinned `tiktoken==0.11.0`,
`o200k_base`, and `encode_ordinary`.
These are documentation counts, excluding tool responses, system instructions,
conditional references outside the selected task, and runtime usage or cost.

| Fixed task | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| First-run setup and first sync | 12,163 | 5,159 | 57.58% |
| Saved-source sync and verification | 8,148 | 2,292 | 71.87% |
| Existing TiXL graph edit | 8,148 | 2,649 | 67.49% |
| Stale or blank output diagnosis | 8,148 | 2,048 | 74.86% |
| Component upgrade and release evidence | 14,481 | 3,971 | 72.58% |

The report records exact readsets and per-file hashes at commit
`daa7c356bdfb7416a4e5d7d17ca346ba0b37f2fa`; subsequent reference or capability
updates can change the current counts. First-run namespace and
preference choices remain required; upgrade work reads onboarding only when
first-run behavior is affected. Detailed protocol, operator, Blender and
discovery references remain available for their respective subtasks.

A forced refresh through the official Blender MCP extension generated both
capability files from the same live evidence. All component coverage was complete
with Blender 5.2.2 LTS, Blender MCP 1.0.3 and TiXL 4.3.0.2 / protocol 1. The detailed
inventory was byte-identical to the previous full report. Missing or corrupt
sidecars prevent evidence reuse; tests also cover a large advertised capability
schema remaining in the detail file instead of expanding the summary.

The rebuilt ZIP includes repository rules, both routers, task references and both
generated capability files. All 36 local Markdown routing links resolved inside
the archive; local notes and capability configuration were excluded. The two
routers passed the skill-format validator.

To reproduce, install the pinned tokenizer in a local environment and run
`python tests/benchmark_documentation_reading.py --output reading-report.json`.
The helper retrieves the baseline files directly from Git, so that commit must
be present locally. Optional `--tokenizer-dependencies` and `--tokenizer-cache`
arguments support an isolated installation and cached encoding data. The
tokenizer is an evidence-generation dependency; normal CI needs no network or
tokenizer installation.

## Bounded diagnostics evidence

The diagnostics helper keeps full graph values, protocol envelopes, exact wire
responses, and log messages in private immutable receipts. Its default JSON
summary is limited to 16 KiB, focuses stable child IDs and neighboring nodes, and
preserves global unresolved counts and retained error counts. Detailed output is
explicit. Log follow rescans retained warnings/errors while avoiding repeated
graph and structure queries; it does not claim a new graph validation.

Protocol 1 has no server session identifier. Sequence continuity is inferred
from a saved entry hash; restart, missing-anchor and discarded-history cases
remain visible. Two historical errors in the running editor were retained in
the live measurements, so those diagnostic summaries correctly returned failure
instead of presenting a clean result. This is retained history, not a finding
that the current change introduced those errors.

The [live diagnostics report](benchmarks/diagnostics-2026-09-27.json) records
actual protocol lines using `tiktoken==0.11.0`, `o200k_base`:

| Observation | Fresh inspection | Subsequent log follow |
| --- | ---: | ---: |
| Protocol calls | 7 | 4 |
| Protocol request tokens | 191 | 123 |
| Raw protocol response tokens | 199,045 | 55,399 |
| Default summary tokens | 3,658 | 1,705 |

The fresh inspection summary reduces caller-facing output by 98.16% compared
with its own raw protocol responses; the log-follow summary reduces it by
96.92%. Request tokens fall by 35.60% for the narrower log-follow task. These
snapshots were taken 0.234 seconds apart, retained the same two errors, and
covered 56 graph children and 103 connections in the inspection only. Log follow
does not repeat that graph validation. No runtime billing or whole-conversation
token savings are claimed. Full receipts duplicate parsed data and exact wire
lines for auditability, so their separate size comparison is not a raw-response
baseline.

To reproduce, collect one inspection and one subsequent log-follow receipt
using the same private output directory, then run:

```powershell
python tests/benchmark_bridge_diagnostics.py --inspect-receipt '<inspect-run>/receipt.json' --logs-receipt '<follow-run>/receipt.json' --tokenizer-deps '<local-tiktoken-install>' --output diagnostics-report.json
```

Private paths contribute to the measured summary counts but are omitted from
the portable report. Command recipe counts are templates, not executed prompt
measurements. New logs and local paths can change repeat-run counts.

Committed-cache checks verified a real four-world, 28-file generation and its
authored source hash. Tests cover tampered payloads, changed sources, incompatible
generations, invalid asset bindings, interrupted captures, restoration readback,
and oversized summary evidence preservation. A legacy flat cache is rejected
when committed-generation evidence is requested.

Opt-in native output captures at 0, 4, 8 and 12 seconds were visually inspected.
All four 3840×2160 PNG hashes matched the prior fresh baseline exactly: cube,
sphere, prism and cylinder remained visible with their expected lighting and
background. The project, selection, output pin, paused time and speed were
restored. This covers four world starts, not every intermediate animation frame.
The helper itself leaves each capture marked as requiring visual review.

The updated add-on installation verified 57 package files with one client file
updated, preserved the foreground Blender scene, and retained saved preferences
in a fresh background Blender process. The official one-shot capability refresh
completed. The rebuilt archive includes the helper and its conditional guide;
the extracted helper imports and displays its CLI help successfully.

See the [diagnostics guide](../.agents/skills/blender-tixl-bridge/references/diagnostics.md)
for commands, evidence scope and failure interpretation. The tokenizer used for
measurements is an optional evidence-generation dependency, not a runtime or CI
dependency.

## Published release updater

The 0.5.0 add-on checks GitHub's latest stable published release once on startup
and on request. It displays a versioned update button only when the release is
newer and includes the exact matching ZIP asset. Auto-update is off by default;
enabling it saves the preference and installs a newer release after the check.
Neither path restarts Blender or changes an unsaved scene. A normal restart loads
the installed code.

Archive tests cover tag/asset matching, size and SHA-256 checks, embedded add-on
version, unsafe paths, duplicate names, symbolic links, and rollback after an
interrupted file replacement. The rebuilt 0.5.0 ZIP passed its own archive
validator with 88 package files. Through Blender MCP, installation verified 58
source package files, the add-on exposed both operators and the toggle, and the
foreground untitled Camera/Cube/Light scene stayed intact. A fresh Blender
process retained the existing TiXL project, editor path, debug mode/port, and
the disabled default for auto-update. The one-shot capability refresh reported
complete coverage. A synthetic future release exercised the real Blender
auto-update state flow with a mocked installer; it reached the install path once
without downloading a release or changing installed files, and the toggle was
restored to off. A separate live Blender check removed the polling timer while
a controlled release worker was running: the controller reattached the timer,
kept one worker, and completed the check. The poll and startup timers persist
across `.blend` loads so a scene change cannot leave the controls stuck.

The release check observed no newer published version at validation time. The
automated tests therefore cover the newer-release installation path; no newer
remote release was installed as part of this validation. Current Blender
preferences and Scene panel screenshots were captured through Blender MCP.
TiXL graph screenshots were refreshed through the debug bridge with zero
unresolved children/connections, and its project, selection, output pin, time,
playback and graph view were restored afterward.
