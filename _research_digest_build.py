"""Minimal offline PEP 517 backend for the Research Digest pure-Python wheel."""

from __future__ import annotations

import base64
import hashlib
import os
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
WHEEL_EXCLUDED_PACKAGE_FILES = {
    "research_digest/analysis/fake.py",
}


def get_requires_for_build_wheel(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: Mapping[str, Any] | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)


def get_requires_for_build_editable(
    config_settings: Mapping[str, Any] | None = None,
) -> list[str]:
    return []


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: Mapping[str, Any] | None = None,
) -> str:
    return _prepare_metadata(metadata_directory)


def _prepare_metadata(metadata_directory: str) -> str:
    metadata = _project_metadata()
    dist_info = _dist_info_name(metadata)
    target = Path(metadata_directory) / dist_info
    target.mkdir(parents=True, exist_ok=True)
    _write_dist_info(target, metadata)
    (target / "RECORD").write_text("", encoding="utf-8")
    return dist_info


def build_wheel(
    wheel_directory: str,
    config_settings: Mapping[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _build_package_wheel(wheel_directory, editable=False)


def build_editable(
    wheel_directory: str,
    config_settings: Mapping[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _build_package_wheel(wheel_directory, editable=True)


def _build_package_wheel(wheel_directory: str, *, editable: bool) -> str:
    metadata = _project_metadata()
    dist_info = _dist_info_name(metadata)
    wheel_name = _wheel_name(metadata)
    wheel_path = Path(wheel_directory) / wheel_name
    wheel_path.parent.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as tmp:
        staging = Path(tmp)
        dist_info_path = staging / dist_info
        dist_info_path.mkdir(parents=True)
        _write_dist_info(dist_info_path, metadata)
        record_entries: list[tuple[str, str, int] | tuple[str, str, str]] = []

        with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if editable:
                _write_archive_bytes(
                    archive,
                    f"{SOURCE_ROOT}\n".encode(),
                    f"{_normalized_distribution(str(metadata['name']))}.pth",
                    record_entries,
                )
            else:
                for path in _package_files():
                    archive_name = path.relative_to(SOURCE_ROOT).as_posix()
                    _write_archive_file(archive, path, archive_name, record_entries)

            for path in sorted(dist_info_path.rglob("*")):
                archive_name = f"{dist_info}/{path.relative_to(dist_info_path).as_posix()}"
                _write_archive_file(archive, path, archive_name, record_entries)

            record_name = f"{dist_info}/RECORD"
            record_entries.append((record_name, "", ""))
            _write_archive_raw(
                archive,
                _record_text(record_entries).encode("utf-8"),
                record_name,
            )

    return wheel_name


def _project_metadata() -> dict[str, Any]:
    payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = payload["project"]
    if not isinstance(project, dict):
        raise TypeError("[project] metadata must be a table")
    return project


def _dist_info_name(metadata: Mapping[str, Any]) -> str:
    return f"{_normalized_distribution(str(metadata['name']))}-{metadata['version']}.dist-info"


def _wheel_name(metadata: Mapping[str, Any]) -> str:
    distribution = _normalized_distribution(str(metadata["name"]))
    return f"{distribution}-{metadata['version']}-py3-none-any.whl"


def _normalized_distribution(name: str) -> str:
    return name.replace("-", "_").replace(".", "_")


def _write_dist_info(dist_info_path: Path, metadata: Mapping[str, Any]) -> None:
    (dist_info_path / "METADATA").write_text(_metadata_text(metadata), encoding="utf-8")
    (dist_info_path / "WHEEL").write_text(_wheel_text(), encoding="utf-8")
    (dist_info_path / "entry_points.txt").write_text(_entry_points_text(metadata), encoding="utf-8")


def _metadata_text(metadata: Mapping[str, Any]) -> str:
    lines = [
        "Metadata-Version: 2.1",
        f"Name: {metadata['name']}",
        f"Version: {metadata['version']}",
        f"Summary: {metadata.get('description', '')}",
        f"Requires-Python: {metadata.get('requires-python', '')}",
    ]
    for dependency in metadata.get("dependencies", []):
        lines.append(f"Requires-Dist: {dependency}")
    optional_dependencies = metadata.get("optional-dependencies", {})
    if isinstance(optional_dependencies, dict):
        for extra, dependencies in sorted(optional_dependencies.items()):
            lines.append(f"Provides-Extra: {extra}")
            if isinstance(dependencies, list):
                for dependency in dependencies:
                    lines.append(f"Requires-Dist: {dependency}; extra == \"{extra}\"")
    lines.append("Description-Content-Type: text/markdown")
    lines.append("")
    readme = metadata.get("readme")
    if isinstance(readme, str):
        lines.append((PROJECT_ROOT / readme).read_text(encoding="utf-8"))
    return "\n".join(lines) + "\n"


def _wheel_text() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: research-digest-local-build",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _entry_points_text(metadata: Mapping[str, Any]) -> str:
    scripts = metadata.get("scripts", {})
    if not isinstance(scripts, dict) or not scripts:
        return ""
    lines = ["[console_scripts]"]
    for name, target in sorted(scripts.items()):
        lines.append(f"{name} = {target}")
    return "\n".join(lines) + "\n"


def _package_files() -> list[Path]:
    package_root = SOURCE_ROOT / "research_digest"
    return sorted(
        path
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        and path.relative_to(SOURCE_ROOT).as_posix() not in WHEEL_EXCLUDED_PACKAGE_FILES
    )


def _write_archive_file(
    archive: zipfile.ZipFile,
    path: Path,
    archive_name: str,
    record_entries: list[tuple[str, str, int] | tuple[str, str, str]],
) -> None:
    data = path.read_bytes()
    mode = 0o755 if os.access(path, os.X_OK) else 0o644
    _write_archive_bytes(archive, data, archive_name, record_entries, mode=mode)


def _write_archive_bytes(
    archive: zipfile.ZipFile,
    data: bytes,
    archive_name: str,
    record_entries: list[tuple[str, str, int] | tuple[str, str, str]],
    *,
    mode: int = 0o644,
) -> None:
    _write_archive_raw(archive, data, archive_name, mode=mode)
    record_entries.append((archive_name, _hash_record(data), len(data)))


def _write_archive_raw(
    archive: zipfile.ZipFile,
    data: bytes,
    archive_name: str,
    *,
    mode: int = 0o644,
) -> None:
    info = zipfile.ZipInfo(archive_name)
    info.date_time = (2026, 8, 17, 0, 0, 0)
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data)


def _hash_record(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={encoded}"


def _record_text(entries: list[tuple[str, str, int] | tuple[str, str, str]]) -> str:
    return "".join(f"{path},{digest},{size}\n" for path, digest, size in entries)
