# Validation and performance measurement

Run the isolated Python regression suite from the repository root:

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
```

The reusable `unit-tests.yml` workflow runs this suite on Windows and Ubuntu for pull requests and branch pushes. `release.yml` depends on that workflow; a failing matrix job prevents ZIP building and release publication. Live Blender and TiXL checks are separate because they need local application installs and a GPU.

## Structured sync measurements

Every sync returns a `metrics` JSON path under its cache's `sync_metrics/` directory. Reports share a run ID across queue, discovery, host sync, and Blender worker lanes. Each lane writes its own file. Completed worker files are listed in the host report; an asynchronous discovery file can arrive later. A skipped discovery reports `resultStatus: skipped`, rather than claiming a probe completed.

Reports record elapsed time, process ID, observed process launches, hashed bytes, committed cache bytes, process memory, and phase aggregates. Phases cover queue and lock wait, discovery, hashing, Blender startup, geometry export, animation and camera baking, validation, publication, graph generation, build, activation, and first evaluation when those operations occur. Startup is measured from the parent's launch timestamp to entry in the Blender worker. Phases can nest; their totals must not be added to derive overall wall time. Windows memory comes from `GetProcessMemoryInfo`; Unix reports process peak RSS. These are process-lifetime peaks, not allocation deltas.

Failed syncs preserve their report, attach its path as `exception.metrics_path`, and print a `SYNC_METRICS_REPORT` record. Reports include a bounded error message. Failure to write measurement files does not replace the export's result or exception.

## Repeatable local benchmarks

Launch `tests/blender_sync_benchmark.py` through Blender MCP in a disposable background Blender process with `--factory-startup`. It creates private fixtures and caches under `examples/.tixl_cache/benchmarks/` and leaves the interactive scene untouched. Its workloads cover a static cube's first/unchanged/edited sync, a 600-frame keyed timeline, three contiguous worlds, eight animated morph keys, and five rapid saved revisions with actual CLI requests. It verifies that the final committed source matches the latest save. Process counts come from launch instrumentation, including failed requests.

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
