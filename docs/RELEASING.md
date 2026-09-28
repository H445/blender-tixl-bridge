# Releasing the Blender–TiXL bridge

The version in `blender_tixl_bridge/__init__.py` is the single source of truth for package and release names.

While the project is alpha, use `0.x.y` versions. Increment the minor number for a feature release and the patch number for a compatible correction.

1. Update `bl_info["version"]` and finish the release-refresh checks.
2. Run the tests and `python build_addon_zip.py`. The output must be `blender-tixl-bridge-<version>.zip`.
3. Commit and push the release changes.
4. Create and push the matching tag, such as `v0.4.0` for add-on version `0.4.0`.

The `Publish add-on release` GitHub Actions workflow checks out Git LFS assets, verifies that the bundled example is a real Blender file, and confirms that the tag and add-on version match. It then creates the GitHub Release with generated notes and uploads the versioned ZIP. A missing LFS asset or mismatched tag fails before anything is published.
