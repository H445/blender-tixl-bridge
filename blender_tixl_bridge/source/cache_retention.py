"""Bounded, cache-scoped retention primitives.

Callers must supply names that are active, referenced, or otherwise pinned.
These helpers do not inspect graph references, process ownership, or open file
handles. Mutations are opt-in with ``dry_run=False``.
"""

from __future__ import annotations

import math
import hashlib
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Pattern


DEFAULT_NAME_PATTERN = r"(?!\.{1,2}$)[A-Za-z0-9][A-Za-z0-9._-]{0,127}"


@dataclass(frozen=True)
class RetentionPolicy:
    """Default bounded policy; a caller may tune all three limits."""

    max_count: int = 8
    max_bytes: int = 512 * 1024 * 1024
    max_age_days: float = 30.0

    def __post_init__(self) -> None:
        if isinstance(self.max_count, bool) or not isinstance(self.max_count, int) or self.max_count < 0:
            raise ValueError("max_count must be a nonnegative integer")
        if isinstance(self.max_bytes, bool) or not isinstance(self.max_bytes, int) or self.max_bytes < 0:
            raise ValueError("max_bytes must be a nonnegative integer")
        if (isinstance(self.max_age_days, bool) or not isinstance(self.max_age_days, (int, float))
                or not math.isfinite(self.max_age_days) or self.max_age_days < 0):
            raise ValueError("max_age_days must be a finite nonnegative number")


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    if callable(checker):
        try:
            return bool(checker())
        except OSError:
            return True
    checker = getattr(os.path, "isjunction", None)
    if callable(checker):
        try:
            return bool(checker(path))
        except OSError:
            return True
    return False


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
        reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return (path.is_symlink() or _is_junction(path)
                or bool(getattr(info, "st_file_attributes", 0) & reparse_attribute))
    except FileNotFoundError:
        # Missing optional cache roots are safe to treat as absent. Dangling
        # links still have an lstat entry and are detected above.
        return False
    except OSError:
        return True


def _has_reparse_ancestor(path: Path) -> Path | None:
    """Find links/junctions before resolution can hide a redirected parent."""
    absolute = Path(os.path.abspath(path))
    chain = list(reversed(absolute.parents)) + [absolute]
    for item in chain:
        if _is_reparse(item):
            return item
    return None


def _name_pattern(value: str | Pattern[str]) -> Pattern[str]:
    if isinstance(value, str):
        return re.compile(value)
    if isinstance(value, re.Pattern):
        return value
    raise TypeError("name_pattern must be a regular expression string or compiled pattern")


def _name(value: object, pattern: Pattern[str]) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError("retention evidence must contain simple child names")
    if "/" in value or "\\" in value or Path(value).name != value:
        raise ValueError("retention evidence must not contain path components")
    if pattern.fullmatch(value) is None:
        raise ValueError("retention evidence does not match the generated-name filter")
    return value


def _safe_root(root: Path, cache_root: Path) -> tuple[Path, Path]:
    root = Path(root)
    cache_root = Path(cache_root)
    absolute_root = Path(os.path.abspath(root))
    absolute_cache = Path(os.path.abspath(cache_root))
    if absolute_root == absolute_cache:
        raise ValueError("retention root must be a child of the cache root")
    link = _has_reparse_ancestor(cache_root) or _has_reparse_ancestor(root)
    if link:
        raise ValueError(f"retention root has a symlink or junction parent: {link}")
    if not cache_root.exists() or not cache_root.is_dir():
        raise ValueError("cache root is missing or is not a directory")
    cache = cache_root.resolve(strict=True)
    if not root.exists():
        resolved_missing = root.resolve(strict=False)
        resolved_missing.relative_to(cache)
        return cache, resolved_missing
    if not root.is_dir():
        raise ValueError("retention root is not a directory")
    resolved = root.resolve(strict=True)
    try:
        relative = resolved.relative_to(cache)
    except ValueError as error:
        raise ValueError("retention root escapes cache root") from error
    if not relative.parts:
        raise ValueError("retention root must be a child of the cache root")
    return cache, resolved


def _walk_evidence(path: Path) -> tuple[int, int, str]:
    """Measure directory contents and identity without following reparse points."""
    total = 0
    newest = path.lstat().st_mtime_ns
    stack = [path]
    inventory = []
    while stack:
        folder = stack.pop()
        if _is_reparse(folder):
            raise ValueError(f"backup tree contains a symlink or junction: {folder.name}")
        with os.scandir(folder) as entries:
            for entry in sorted(entries, key=lambda row: row.name.casefold()):
                child = Path(entry.path)
                if _is_reparse(child):
                    raise ValueError(f"backup tree contains a symlink or junction: {child.name}")
                info = entry.stat(follow_symlinks=False)
                newest = max(newest, info.st_mtime_ns)
                relative = child.relative_to(path).as_posix()
                inventory.append({
                    "path": relative,
                    "mode": stat.S_IFMT(info.st_mode),
                    "size": info.st_size,
                    "mtimeNs": info.st_mtime_ns,
                    "device": getattr(info, "st_dev", None),
                    "inode": getattr(info, "st_ino", None),
                })
                if stat.S_ISDIR(info.st_mode):
                    stack.append(child)
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                else:
                    raise ValueError(f"backup tree contains a non-regular entry: {child.name}")
    encoded = json.dumps(sorted(inventory, key=lambda row: row["path"]),
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return total, newest, hashlib.sha256(encoded).hexdigest()


def _file_evidence(path: Path, name: str) -> tuple[int, int, str]:
    """Return stable metadata evidence using the same path-based stat each time."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"retention candidate has the wrong type: {name}")
    size, newest = info.st_size, info.st_mtime_ns
    evidence = hashlib.sha256(json.dumps({
        "name": name, "size": info.st_size, "mtimeNs": info.st_mtime_ns,
        "device": getattr(info, "st_dev", None),
        "inode": getattr(info, "st_ino", None),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return size, newest, evidence


def _entry_rows(root: Path, kind: str, pattern: Pattern[str]) -> list[dict]:
    rows = []
    with os.scandir(root) as entries:
        for entry in entries:
            name = entry.name
            if pattern.fullmatch(name) is None:
                continue
            path = Path(entry.path)
            if _is_reparse(path):
                raise ValueError(f"retention candidate is a symlink or junction: {name}")
            info = path.lstat()
            if kind == "directories" and stat.S_ISDIR(info.st_mode):
                size, newest, evidence = _walk_evidence(path)
            elif kind == "files" and stat.S_ISREG(info.st_mode):
                size, newest, evidence = _file_evidence(path, name)
            else:
                raise ValueError(f"retention candidate has the wrong type: {name}")
            rows.append({"name": name, "path": path, "bytes": size,
                         "mtimeNs": newest, "rootMtimeNs": info.st_mtime_ns,
                         "evidence": evidence})
    return rows


def _plan(
    root: Path,
    cache_root: Path,
    policy: RetentionPolicy,
    *,
    kind: str,
    name_pattern: str | Pattern[str],
    pinned_names: Iterable[str] = (),
    referenced_names: Iterable[str] = (),
    failed_names: Iterable[str] = (),
    newest_always_keep: int = 1,
    now: float | None = None,
) -> tuple[dict, list[dict]]:
    if not isinstance(policy, RetentionPolicy):
        return {"status": "aborted", "reason": "invalid retention policy"}, []
    if isinstance(newest_always_keep, bool) or not isinstance(newest_always_keep, int) or newest_always_keep < 0:
        return {"status": "aborted", "reason": "newest_always_keep must be a nonnegative integer"}, []
    if now is not None and (isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now)):
        return {"status": "aborted", "reason": "now must be a finite timestamp"}, []
    try:
        pattern = _name_pattern(name_pattern)
        cache, resolved_root = _safe_root(Path(root), Path(cache_root))
        if not resolved_root.exists():
            return {"status": "empty", "root": str(root), "kept": [], "deleted": [],
                    "bytesBefore": 0, "bytesAfter": 0, "budgetExceeded": {}}, []
        # The root must remain below the resolved cache even after validation.
        resolved_root.relative_to(cache)
        rows = _entry_rows(resolved_root, kind, pattern)
        by_name = {row["name"]: row for row in rows}
        supplied_names = []
        for group in (pinned_names, referenced_names, failed_names):
            if isinstance(group, (str, bytes)):
                raise ValueError("retention evidence must be a sequence of names")
            supplied_names.extend(_name(value, pattern) for value in tuple(group))
        missing = sorted(set(supplied_names) - set(by_name))
        if missing:
            raise ValueError("pinned or referenced retention entry is missing: " + ", ".join(missing))
        pinned = set(supplied_names)
    except (OSError, RuntimeError, ValueError, re.error, TypeError) as error:
        return {"status": "aborted", "reason": str(error), "kept": [], "deleted": []}, []

    rows.sort(key=lambda row: (-row["mtimeNs"], row["name"].casefold(), row["name"]))
    always = {row["name"] for row in rows[:newest_always_keep]}
    kept = pinned | always
    protected_rows = [row for row in rows if row["name"] in kept]
    kept_count = len(protected_rows)
    kept_bytes = sum(row["bytes"] for row in protected_rows)
    pinned_rows = [row for row in rows if row["name"] in pinned]
    pinned_bytes = sum(row["bytes"] for row in pinned_rows)
    unprotected_rows = [row for row in rows if row["name"] not in kept]
    current = time.time() if now is None else now
    cutoff = current - float(policy.max_age_days) * 86400
    delete_names = set()
    for row in unprotected_rows:
        expired = row["mtimeNs"] / 1_000_000_000 < cutoff
        count_full = kept_count >= policy.max_count
        byte_full = kept_bytes + row["bytes"] > policy.max_bytes
        if expired or count_full or byte_full:
            delete_names.add(row["name"])
        else:
            kept.add(row["name"])
            kept_count += 1
            kept_bytes += row["bytes"]

    over_count = max(0, len(kept) - policy.max_count)
    over_bytes = max(0, kept_bytes - policy.max_bytes)
    over_age = [row["name"] for row in protected_rows if row["mtimeNs"] / 1_000_000_000 < cutoff]
    before = sum(row["bytes"] for row in rows)
    plan = {
        "status": "planned",
        "kind": kind,
        "kept": sorted(kept),
        "pinned": sorted(pinned),
        "newestAlwaysKeep": sorted(always),
        "wouldDelete": [row["name"] for row in rows if row["name"] in delete_names],
        "deleted": [],
        "bytesBefore": before,
        "bytesAfter": kept_bytes,
        "budgetExceeded": {"count": over_count, "bytes": over_bytes, "ageProtected": over_age},
        "pinnedBudgetExceeded": {
            "count": max(0, len(pinned_rows) - policy.max_count),
            "bytes": max(0, pinned_bytes - policy.max_bytes),
        },
        "limits": {"count": policy.max_count, "bytes": policy.max_bytes,
                   "ageDays": float(policy.max_age_days)},
    }
    return plan, [row for row in rows if row["name"] in delete_names]


def _prune(
    root: Path,
    cache_root: Path,
    policy: RetentionPolicy = RetentionPolicy(),
    *,
    kind: str,
    name_pattern: str | Pattern[str] = DEFAULT_NAME_PATTERN,
    pinned_names: Iterable[str] = (),
    referenced_names: Iterable[str] = (),
    failed_names: Iterable[str] = (),
    newest_always_keep: int = 1,
    dry_run: bool = True,
    now: float | None = None,
) -> dict:
    plan, deletions = _plan(root, cache_root, policy, kind=kind,
                            name_pattern=name_pattern, pinned_names=pinned_names,
                            referenced_names=referenced_names, failed_names=failed_names,
                            newest_always_keep=newest_always_keep, now=now)
    if plan.get("status") == "aborted" or plan.get("status") == "empty" or dry_run:
        return plan
    try:
        cache, resolved_root = _safe_root(Path(root), Path(cache_root))
        resolved_root.relative_to(cache)
        for row in deletions:
            current_cache, current_root = _safe_root(Path(root), Path(cache_root))
            if current_cache != cache or current_root != resolved_root:
                raise ValueError("retention root changed after planning")
            current_root.relative_to(current_cache)
            path = current_root / row["name"]
            if _is_reparse(path):
                raise ValueError(f"retention candidate became a symlink or junction: {row['name']}")
            # Re-measure immediately before mutation to avoid deleting an entry
            # that grew, changed type, or gained a linked descendant after plan.
            if kind == "directories":
                size, newest, evidence = _walk_evidence(path)
            else:
                size, newest, evidence = _file_evidence(path, row["name"])
            if (size != row["bytes"] or newest != row["mtimeNs"]
                    or evidence != row["evidence"]):
                raise ValueError(f"retention candidate changed after planning: {row['name']}")
            if kind == "directories":
                shutil.rmtree(path)
            else:
                path.unlink()
            plan["deleted"].append(row["name"])
    except (OSError, RuntimeError, ValueError) as error:
        plan["status"] = "aborted"
        plan["reason"] = str(error)
        return plan
    plan["status"] = "pruned"
    # Report the measured remainder, including retained entries.
    try:
        _, remaining_root = _safe_root(Path(root), Path(cache_root))
        remaining = _entry_rows(remaining_root, kind, _name_pattern(name_pattern))
        plan["bytesAfter"] = sum(row["bytes"] for row in remaining)
        plan["kept"] = sorted(row["name"] for row in remaining)
    except (OSError, RuntimeError, ValueError, re.error, TypeError) as error:
        plan["status"] = "aborted"
        plan["reason"] = f"could not verify retention result: {error}"
    return plan


def prune_directories(
    root: Path,
    cache_root: Path,
    policy: RetentionPolicy = RetentionPolicy(),
    *,
    name_pattern: str | Pattern[str] = DEFAULT_NAME_PATTERN,
    pinned_names: Iterable[str] = (),
    referenced_names: Iterable[str] = (),
    failed_names: Iterable[str] = (),
    newest_always_keep: int = 1,
    dry_run: bool = True,
    now: float | None = None,
) -> dict:
    """Plan or prune direct-child backup/generated directories under a cache."""
    return _prune(root, cache_root, policy, kind="directories", name_pattern=name_pattern,
                  pinned_names=pinned_names, referenced_names=referenced_names,
                  failed_names=failed_names, newest_always_keep=newest_always_keep,
                  dry_run=dry_run, now=now)


def prune_files(
    root: Path,
    cache_root: Path,
    policy: RetentionPolicy = RetentionPolicy(),
    *,
    name_pattern: str | Pattern[str] = DEFAULT_NAME_PATTERN,
    pinned_names: Iterable[str] = (),
    referenced_names: Iterable[str] = (),
    failed_names: Iterable[str] = (),
    newest_always_keep: int = 1,
    dry_run: bool = True,
    now: float | None = None,
) -> dict:
    """Plan or prune direct-child regular files; open writers must be pinned."""
    return _prune(root, cache_root, policy, kind="files", name_pattern=name_pattern,
                  pinned_names=pinned_names, referenced_names=referenced_names,
                  failed_names=failed_names, newest_always_keep=newest_always_keep,
                  dry_run=dry_run, now=now)
