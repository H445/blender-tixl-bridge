# Releasing the Blender–TiXL bridge

The version in `blender_tixl_bridge/__init__.py` is the single source of truth for package and release names.

1. Update `bl_info["version"]` and finish the release-refresh checks.
2. Run the tests and `python build_addon_zip.py`. The output must be `blender-tixl-bridge-<version>.zip`.
3. Commit and push the release changes.
4. Create and push the matching tag, such as `v1.3.1` for add-on version `1.3.1`.

The `Publish add-on release` GitHub Actions workflow verifies that the tag and add-on version match, creates the GitHub Release with generated notes, and uploads the versioned ZIP. A mismatched tag fails before anything is published.
