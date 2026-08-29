#!/usr/bin/env python3
"""Verify an exact release-asset directory without importing project runtime code."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

MANIFEST_NAME: Final = "SHA256SUMS"


class VerificationError(RuntimeError):
    """Raised when release assets differ from the explicit qualified set."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_expected(values: Sequence[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for value in values:
        name, separator, digest = value.partition("=")
        if (
            not separator
            or Path(name).name != name
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or name in expected
        ):
            raise VerificationError(f"Invalid expected asset declaration: {value!r}")
        expected[name] = digest
    if MANIFEST_NAME not in expected:
        raise VerificationError(f"Expected assets must include {MANIFEST_NAME}.")
    return expected


def parse_manifest(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, name = line.partition("  ")
        if (
            not separator
            or Path(name).name != name
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or name in entries
        ):
            raise VerificationError(f"Malformed {MANIFEST_NAME} entry: {line!r}")
        entries[name] = digest
    return entries


def verify_assets(asset_dir: Path, expected: dict[str, str]) -> None:
    root = asset_dir.resolve(strict=True)
    entries = list(root.iterdir())
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise VerificationError("Asset directory contains a symlink or non-file entry.")
    actual_names = {entry.name for entry in entries}
    if actual_names != set(expected):
        raise VerificationError(
            f"Asset inventory differs: expected {sorted(expected)}, got {sorted(actual_names)}"
        )
    for name, expected_digest in expected.items():
        actual_digest = sha256(root / name)
        if actual_digest != expected_digest:
            raise VerificationError(
                f"SHA-256 mismatch for {name}: expected {expected_digest}, got {actual_digest}"
            )

    manifest = parse_manifest((root / MANIFEST_NAME).read_text(encoding="ascii"))
    payloads = {name: digest for name, digest in expected.items() if name != MANIFEST_NAME}
    if manifest != payloads:
        raise VerificationError(
            f"{MANIFEST_NAME} entries differ from the explicit expected payload set."
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--expected", action="append", default=[], metavar="NAME=SHA256")
    args = parser.parse_args(argv)
    try:
        verify_assets(args.asset_dir, parse_expected(args.expected))
    except (OSError, VerificationError) as exc:
        parser.error(str(exc))
    print("Exact release asset inventory and SHA-256 values verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
