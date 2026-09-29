# Graph layout rules for agents

Use these rules for any TiXL composition whose nodes or connections have grown
or whose overview is difficult to read. The layout must follow the *current*
graph, including user effects, rather than a saved screenshot or fixed IDs.

1. Read `getContext`, `getGraphState(includeDefaults=False)`, and `getGraphView`
   through the debug bridge. Read the matching `.t3` and `.t3ui` files. Confirm
   live child positions match the saved UI. If they differ, preserve the editor
   layout and ask the user to save before editing the files. Never infer a clean
   state from a paused playhead.
2. Stage a new `.t3ui` outside `Symbols` with `tools/layout_tixl_graph.py
   --graph <home.t3> --ui <home.t3ui> --output <staged.t3ui>`. The helper uses
   the current connection DAG, places the longest path left to right, moves
   side branches near their consumers, separates semantic lanes, and swaps
   lanes when that lowers wire crossings. It changes positions only. It fails
   closed on missing child IDs, outside connections, or cycles. Review those
   graphs individually rather than inventing positions.
3. Compare node and connection counts, child IDs, non-position UI fields, and
   the crossing metric. Check that positions are unique and that sockets have
   enough space. Make a small graph preview if needed. Do not replace user
   topology, input values, TimeClips, or output routing to improve appearance.
4. Apply with `--output <home.t3ui> --backup <path outside Symbols>` after the
   editor is known clean. Close it through `shutdown` and restart with the
   configured bridge and full process permissions. `reload` alone can retain
   old graph data. Do not place a duplicate `.t3` or `.t3ui` in `Symbols`.
5. Re-read `getGraphState`, focus the whole graph and representative stages,
   capture graph screenshots, and compare several output frames plus the loop
   seam. Confirm every child and edge still resolves and the render is unchanged.
   Restore the user's playhead and graph view where practical.

For newly generated homes, `layout_home` seeds dynamic world lanes. Existing
homes preserve editor positions during sync. Run the connected-graph helper
only for an explicit layout request or a new home before user arrangement;
never silently overwrite a saved user layout when a sync adds nodes.
