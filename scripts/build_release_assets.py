#!/usr/bin/env python3
"""Build the explicit Research Digest end-user release asset set."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import _research_digest_build as wheel_backend  # noqa: E402

VERSION = "0.5.0"
WHEEL_NAME = f"research_digest-{VERSION}-py3-none-any.whl"
ASSET_SOURCES = {
    "install-research-digest.py": PROJECT_ROOT / "installers" / "install_research_digest.py",
    "install-research-digest-macos.sh": (
        PROJECT_ROOT / "installers" / "install-research-digest-macos.sh"
    ),
    "install-research-digest-windows.ps1": (
        PROJECT_ROOT / "installers" / "install-research-digest-windows.ps1"
    ),
}
FORBIDDEN_WHEEL_PREFIXES = ("tests/", "docs/", ".github/")
FORBIDDEN_WHEEL_NAMES = {"AGENTS.md", "research_digest/analysis/fake.py"}


def build_release_assets(output_directory: Path) -> list[Path]:
    output = output_directory.expanduser().absolute()
    if output.is_symlink():
        raise RuntimeError("Release output directory may not be a symbolic link.")
    output.mkdir(parents=True, exist_ok=True)
    owned_names = {WHEEL_NAME, "SHA256SUMS", *ASSET_SOURCES}
    symlinks = sorted(name for name in owned_names if (output / name).is_symlink())
    if symlinks:
        raise RuntimeError(f"Release output contains symbolic-link asset paths: {symlinks}")
    wheel_name = wheel_backend.build_wheel(str(output))
    if wheel_name != WHEEL_NAME:
        raise RuntimeError(f"Built unexpected wheel {wheel_name!r}; expected {WHEEL_NAME!r}.")
    wheel_path = output / wheel_name
    inspect_wheel_boundary(wheel_path)

    assets = [wheel_path]
    for name, source in ASSET_SOURCES.items():
        destination = output / name
        shutil.copyfile(source, destination)
        if name.endswith(".sh") or name.endswith(".py"):
            destination.chmod(0o755)
        assets.append(destination)

    manifest = output / "SHA256SUMS"
    lines = [f"{sha256(path)}  {path.name}\n" for path in sorted(assets)]
    manifest.write_text("".join(lines), encoding="ascii")
    manifest.chmod(0o644)
    return [*sorted(assets), manifest]


def inspect_wheel_boundary(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    forbidden = sorted(
        name
        for name in names
        if name in FORBIDDEN_WHEEL_NAMES
        or any(name.startswith(prefix) for prefix in FORBIDDEN_WHEEL_PREFIXES)
    )
    if forbidden:
        raise RuntimeError(f"Wheel contains forbidden development entries: {forbidden}")
    required = {
        "research_digest/__init__.py",
        "research_digest/cli.py",
        "research_digest/distribution.py",
        "research_digest/ui/app.py",
        "research_digest/py.typed",
    }
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"Wheel is missing required runtime entries: {missing}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist")
    args = parser.parse_args()
    for path in build_release_assets(args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
