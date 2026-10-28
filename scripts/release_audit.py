"""Offline, deterministic source-manifest audit. No network, Docker or mutations."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "MANIFEST.json"
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "build", "dist"}
ALLOWED_SKIP_SUFFIXES = {".pyc", ".pyo"}


def source_files() -> list[Path]:
    files = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if any(x in SKIP_DIRS or x.endswith(".egg-info") for x in rel.parts):
            continue
        if rel.as_posix().startswith(("local-reports/", "local-evidence/")):
            raise ValueError(f"Local evidence detected inside release source: {rel}")
        if p.is_symlink():
            raise ValueError(f"Unexpected symlink inside release source: {rel}")
        if p.is_file() and rel.as_posix() != "MANIFEST.json" and p.suffix not in ALLOWED_SKIP_SUFFIXES:
            files.append(p)
    return sorted(files, key=lambda p:p.relative_to(ROOT).as_posix())


def audit() -> None:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if data.get("version") != "1.0.0":
        raise ValueError("Expected v1.0.0 manifest")
    expected = data.get("files")
    if not isinstance(expected, dict):
        raise ValueError("Missing SHA-256 file dictionary")
    actual = {}
    for p in source_files():
        actual[p.relative_to(ROOT).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extras = sorted(set(actual) - set(expected))
        raise ValueError(f"Manifest paths mismatch: missing={missing}, extras={extras}")
    failures = [k for k,v in actual.items() if expected[k] != v]
    if failures:
        raise ValueError(f"SHA-256 mismatches: {failures}")
    print(f"Release source manifest PASS: {len(actual)} files, version {data['version']}")
    print("Note: SHA-256 is a consistency checksum, not a signature or proof of origin.")


if __name__ == "__main__":
    try:
        audit()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Release audit FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
