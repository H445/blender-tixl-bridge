"""Check and install published bridge ZIPs without importing Blender.

Network work can run on a short-lived worker thread. Installation belongs to
Blender's main thread and takes effect after a normal Blender restart.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import uuid
import urllib.error
import urllib.request
from zipfile import ZipFile, BadZipFile


RELEASE_API = "https://api.github.com/repos/H445/blender-tixl-bridge/releases/latest"
RELEASE_WEB = "https://github.com/H445/blender-tixl-bridge/releases"
PACKAGE_PREFIX = "blender_tixl_bridge/"
MAX_METADATA = 1024 * 1024
MAX_ARCHIVE = 50 * 1024 * 1024
MAX_UNPACKED = 256 * 1024 * 1024
MAX_ENTRY = 64 * 1024 * 1024
MAX_FILES = 512
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "Blender-TiXL-Bridge-Updater"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}


def _version(value):
    if not isinstance(value, (tuple, list)) or len(value) != 3 or any(
            type(part) is not int or part < 0 for part in value):
        raise ValueError("Invalid three-part add-on version")
    return tuple(value)


def validate_release(payload: dict, current_version: tuple[int, int, int]) -> dict | None:
    """Return the latest newer stable release with its exact expected ZIP asset."""
    current = _version(current_version)
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("Latest release metadata is invalid or not stable")
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError("Published release tag must be vMAJOR.MINOR.PATCH")
    version = tuple(int(part) for part in tag[1:].split("."))
    if version <= current:
        return None
    expected_name = f"blender-tixl-bridge-{tag[1:]}.zip"
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Published release has no asset list")
    candidates = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == expected_name]
    if len(candidates) != 1:
        raise ValueError("Published release is missing its unique versioned ZIP asset")
    asset = candidates[0]
    url = asset.get("browser_download_url")
    expected_url = f"https://github.com/H445/blender-tixl-bridge/releases/download/{tag}/{expected_name}"
    if url != expected_url:
        raise ValueError("Release asset URL is outside the official repository")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE:
        raise ValueError("Release asset size is missing or exceeds the limit")
    digest = asset.get("digest")
    if digest is not None:
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise ValueError("Release asset has an unsupported digest")
        digest = digest.split(":", 1)[1].lower()
    return {"version": version, "tag": tag, "asset_url": url,
            "asset_size": size, "digest": digest,
            "release_url": f"https://github.com/H445/blender-tixl-bridge/releases/tag/{tag}"}


def _read_limited(response, limit):
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release download exceeds the size limit")
    if not response.geturl().startswith("https://"):
        raise ValueError("Release download did not stay on HTTPS")
    return data


def fetch_latest_release(current_version, opener=urllib.request.urlopen):
    """Check the official public GitHub release endpoint once."""
    request = urllib.request.Request(RELEASE_API, headers=HEADERS)
    try:
        with opener(request, timeout=10) as response:
            payload = json.loads(_read_limited(response, MAX_METADATA))
    except urllib.error.HTTPError as error:
        if error.code == 404:  # A repository with no published releases yet.
            return None
        raise
    return validate_release(payload, current_version)


def download_release(release, opener=urllib.request.urlopen):
    """Download the exact published asset and reject incomplete/oversized data."""
    request = urllib.request.Request(release["asset_url"], headers=HEADERS)
    with opener(request, timeout=30) as response:
        data = _read_limited(response, MAX_ARCHIVE)
    if len(data) != release["asset_size"]:
        raise ValueError("Release asset size differs from published metadata")
    return data


def _archive_version(source):
    tree = ast.parse(source.decode("utf-8"), filename="release __init__.py")
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "bl_info"
                                                  for target in node.targets):
            data = ast.literal_eval(node.value)
            return _version(data["version"])
    raise ValueError("Release ZIP lacks add-on version metadata")


def _safe_relative_parts(name):
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise ValueError("Release ZIP contains an unsafe path")
    parts = name.split("/")
    if any(not part or part in (".", "..") or part.endswith((" ", "."))
           or any(char in part for char in ':<>"|?*')
           or part.split(".", 1)[0].upper() in WINDOWS_RESERVED for part in parts):
        raise ValueError("Release ZIP contains an unsafe path")
    return tuple(parts)


def validate_archive(data: bytes, expected_version: tuple[int, int, int],
                     expected_digest: str | None = None) -> dict[str, bytes]:
    """Verify a complete published ZIP and return package-relative file bytes."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_ARCHIVE:
        raise ValueError("Release ZIP size is invalid")
    if expected_digest is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or hashlib.sha256(data).hexdigest() != expected_digest:
            raise ValueError("Release ZIP SHA-256 differs from published digest")
    files = {}
    seen = set()
    total = 0
    try:
        archive = ZipFile(io.BytesIO(data))
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError("Release ZIP contains too many entries")
        for info in infos:
            name = info.filename
            if info.is_dir() and name.endswith("/"):
                name = name[:-1]
            parts = _safe_relative_parts(name)
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError("Release ZIP contains a symbolic link")
            if info.is_dir():
                continue
            if not name.startswith(PACKAGE_PREFIX) or len(parts) < 2:
                raise ValueError("Release ZIP contains a file outside the add-on")
            relative = "/".join(parts[1:])
            folded = relative.casefold()
            if folded in seen:
                raise ValueError("Release ZIP contains duplicate package paths")
            seen.add(folded)
            if info.file_size > MAX_ENTRY or total + info.file_size > MAX_UNPACKED:
                raise ValueError("Release ZIP expands past the size limit")
            total += info.file_size
            with archive.open(info) as stream:
                content = stream.read(info.file_size + 1)
            if len(content) != info.file_size:
                raise ValueError("Release ZIP entry size differs from metadata")
            files[relative] = content
    except BadZipFile as error:
        raise ValueError("Release asset is not a valid ZIP") from error
    if "__init__.py" not in files or "source/release_update.py" not in files:
        raise ValueError("Release ZIP is missing required add-on files")
    if _archive_version(files["__init__.py"]) != _version(expected_version):
        raise ValueError("Release ZIP version differs from its published tag")
    return files


def install_package(files: dict[str, bytes], addon_root: Path) -> None:
    """Replace package files in place, restoring touched files on failure.

    Unknown user files and Blender's separately stored preferences are untouched.
    The running module is not reloaded; Blender must restart to use new code.
    """
    root = Path(addon_root).resolve()
    if root.name != "blender_tixl_bridge" or not (root / "__init__.py").is_file():
        raise ValueError("Update destination is not the installed bridge add-on")
    if not files or "__init__.py" not in files:
        raise ValueError("No validated add-on files were provided")
    originals = {}
    touched = []
    try:
        for relative in sorted(files, key=lambda name: (name == "__init__.py", name)):
            parts = _safe_relative_parts(relative)
            target = root.joinpath(*parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("Update file escapes the add-on directory")
            if not isinstance(files[relative], bytes):
                raise ValueError("Update file content is invalid")
            target.parent.mkdir(parents=True, exist_ok=True)
            originals[target] = target.read_bytes() if target.is_file() else None
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(files[relative])
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            touched.append(target)
    except Exception as primary:
        failures = []
        for target in reversed(touched):
            try:
                original = originals[target]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    temporary = target.with_name(target.name + ".rollback." + uuid.uuid4().hex)
                    try:
                        temporary.write_bytes(original)
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
            except Exception as error:
                failures.append(str(error))
        if failures:
            raise RuntimeError("Update failed and rollback was incomplete: " + "; ".join(failures)) from primary
        raise
