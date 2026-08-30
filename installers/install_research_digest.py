#!/usr/bin/env python3
"""Standalone installer for the versioned Research Digest wheel runtime.

This file deliberately imports only the Python standard library.  It is a
release asset, not part of the installed ``research_digest`` package.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import venv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

VERSION = "0.5.0"
RELEASE_TAG = f"v{VERSION}"
RELEASE_BASE_URL = (
    "https://github.com/inaeyk/research-digest/releases/download/" + RELEASE_TAG
)
WHEEL_NAME = f"research_digest-{VERSION}-py3-none-any.whl"
MANIFEST_NAME = "SHA256SUMS"
OWNER = "org.research-digest.private-runtime.v1"
STATE_SCHEMA = 1
ROOT_MARKER = ".research-digest-runtime-root.json"
VERSION_MARKER = ".research-digest-runtime.json"
CURRENT_STATE = "current.json"
PREVIOUS_STATE = "previous.json"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256_PATTERN = re.compile(r"^([0-9a-fA-F]{64})[ \t]+[*]?([^/\\]+)$")
SHA256_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PURGE_CONFIRMATION = "DELETE MY RESEARCH DIGEST DATA"


class InstallError(RuntimeError):
    """A safe end-user installation or removal could not be completed."""


@dataclass(frozen=True)
class PurgePlan:
    directories: tuple[Path, ...]
    files: tuple[Path, ...]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.show_version:
        print(f"Research Digest installer {VERSION}")
        return 0
    try:
        if args.action == "install":
            result = install(
                asset_dir=args.asset_dir,
                base_url=args.base_url,
                distro=args.distro,
                runtime_root=args.runtime_root,
            )
            _print_install_result(result)
        elif args.action == "uninstall":
            result = uninstall(
                remove_schedule=bool(args.remove_schedule),
                purge_data=bool(args.purge_data),
                confirmation=args.confirm,
                runtime_root=args.runtime_root,
            )
            _print_uninstall_result(result)
        else:
            parser.print_help(sys.stderr)
            return 2
    except InstallError as exc:
        print(f"Research Digest installer failed: {exc}", file=sys.stderr)
        return 1
    return 0


def install(
    *,
    asset_dir: Path | None = None,
    base_url: str = RELEASE_BASE_URL,
    distro: str | None = None,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    """Install, verify, and activate one exact wheel without touching user data."""

    _require_supported_platform()
    _require_supported_python()
    root = _runtime_root(runtime_root)

    with tempfile.TemporaryDirectory(prefix="research-digest-assets-") as temporary:
        assets = Path(temporary)
        manifest_path = _obtain_asset(
            MANIFEST_NAME,
            destination=assets / MANIFEST_NAME,
            asset_dir=asset_dir,
            base_url=base_url,
        )
        manifest = parse_sha256_manifest(manifest_path.read_text(encoding="utf-8"))
        expected_hash = manifest.get(WHEEL_NAME)
        if expected_hash is None:
            raise InstallError(f"{MANIFEST_NAME} has no entry for {WHEEL_NAME}.")
        wheel_path = _obtain_asset(
            WHEEL_NAME,
            destination=assets / WHEEL_NAME,
            asset_dir=asset_dir,
            base_url=base_url,
        )
        verify_sha256(wheel_path, expected_hash)
        _prepare_owned_root(root)

        version_root = root / VERSION
        reused = version_root.exists()
        if reused:
            command = _validate_installed_version(
                version_root,
                expected_wheel_sha256=expected_hash,
            )
        else:
            command = _create_versioned_runtime(
                root=root,
                wheel_path=wheel_path,
                wheel_sha256=expected_hash,
            )

    verification = verify_runtime(command)
    activation = _activate_runtime(
        command=command,
        root=root,
        distro=distro,
    )
    return {
        "version": VERSION,
        "runtime_root": str(root),
        "command": str(command),
        "reused": reused,
        "verification": verification,
        "activation": activation,
    }


def uninstall(
    *,
    remove_schedule: bool,
    purge_data: bool,
    confirmation: str | None,
    runtime_root: Path | None = None,
) -> dict[str, object]:
    """Remove owned runtime surfaces while preserving personal data by default."""

    _require_supported_platform()
    if purge_data and confirmation != PURGE_CONFIRMATION:
        raise InstallError(
            "Destructive purge requires --confirm " + repr(PURGE_CONFIRMATION) + "."
        )
    purge_plan = _build_purge_plan() if purge_data else None
    root = _runtime_root(runtime_root)
    if not root.exists():
        if purge_data:
            assert purge_plan is not None
            _purge_personal_data(purge_plan)
            return {
                "removed": False,
                "data_preserved": False,
                "message": "Runtime was absent; personal data was explicitly purged.",
            }
        return {"removed": False, "data_preserved": True, "message": "Runtime is absent."}
    if root.is_symlink():
        raise InstallError("Private runtime root may not be a symbolic link.")
    _validate_private_directory(root)
    _read_owned_json(root / ROOT_MARKER)
    current = _read_optional_owned_json(root / CURRENT_STATE)
    command = _command_from_state(current)
    if command is None:
        raise InstallError("Current runtime state is missing; refusing an ambiguous removal.")
    _validate_owned_runtime_root_contents(root)

    database = _db_path()
    if database.exists():
        status = _run_json(command, "status", "--json")
        if status.get("run_lock") is not None:
            raise InstallError("A digest is active; cancel or finish it before uninstalling.")
    schedule = _run_json(command, "schedule", "status", "--json")
    if bool(schedule.get("installed")) and not remove_schedule:
        raise InstallError(
            "A daily schedule is installed. Rerun with --remove-schedule to remove the "
            "owned schedule, or leave the runtime installed."
        )
    if bool(schedule.get("installed")):
        _run_checked(command, "schedule", "remove", "--json")
    _run_checked(command, "ui-stop", "--json")
    _run_checked(command, "uninstall-launcher", "--json")
    _remove_owned_runtime_root(root)

    data_preserved = True
    if purge_data:
        assert purge_plan is not None
        _purge_personal_data(purge_plan)
        data_preserved = False
    return {
        "removed": True,
        "data_preserved": data_preserved,
        "schedule_removed": bool(schedule.get("installed")),
    }


def parse_sha256_manifest(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        match = SHA256_PATTERN.fullmatch(line)
        if match is None:
            raise InstallError(f"Malformed SHA-256 manifest line {line_number}.")
        digest, name = match.groups()
        if name in entries:
            raise InstallError(f"Duplicate SHA-256 manifest entry for {name}.")
        entries[name] = digest.lower()
    return entries


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise InstallError(f"Could not read downloaded asset {path.name}.") from exc
    if not hmac.compare_digest(digest.hexdigest(), expected.lower()):
        raise InstallError(f"SHA-256 verification failed for {path.name}; nothing was installed.")


def verify_runtime(command: Path) -> dict[str, object]:
    version = _run_checked(command, "--version").stdout.strip()
    expected = f"research-digest {VERSION}"
    if version != expected:
        raise InstallError(f"Installed CLI reported {version!r}; expected {expected!r}.")
    doctor = _run_checked(command, "doctor").stdout
    if "Failures: 0" not in doctor:
        raise InstallError("Installed CLI doctor did not report Failures: 0.")
    ui_status = _run_json(command, "ui-status", "--json")
    if ui_status.get("status") != "completed":
        raise InstallError("Installed CLI UI status self-check failed.")
    return {
        "version": version,
        "doctor_failures": 0,
        "ui_state": ui_status.get("state"),
    }


def _create_versioned_runtime(
    *,
    root: Path,
    wheel_path: Path,
    wheel_sha256: str,
) -> Path:
    version_root = root / VERSION
    if version_root.exists() or version_root.is_symlink():
        raise InstallError("Refusing to replace an existing versioned runtime.")
    try:
        version_root.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise InstallError("The versioned runtime appeared concurrently; retry safely.") from exc
    try:
        # A venv may not be renamed after creation: generated console-script
        # shebangs contain its absolute path.  This new version directory is
        # therefore built in place but remains inactive until all checks pass.
        environment = version_root / "venv"
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=True).create(environment)
        python = environment / "bin" / "python"
        _run_checked(
            python,
            "-m",
            "pip",
            "--disable-pip-version-check",
            "--no-input",
            "install",
            str(wheel_path),
        )
        command = environment / "bin" / "research-digest"
        verify_runtime(command)
        _atomic_json(
            version_root / VERSION_MARKER,
            _owned_payload(version=VERSION, wheel_sha256=wheel_sha256),
        )
        return _validate_installed_version(
            version_root,
            expected_wheel_sha256=wheel_sha256,
        )
    except BaseException:
        _remove_exact_version_under_construction(version_root, root=root)
        raise


def _validate_installed_version(
    version_root: Path,
    *,
    expected_wheel_sha256: str,
) -> Path:
    if version_root.is_symlink() or version_root.name != VERSION:
        raise InstallError("The versioned runtime path is unsafe.")
    _validate_private_directory(version_root)
    environment = version_root / "venv"
    if environment.is_symlink():
        raise InstallError("The private virtual environment may not be a symbolic link.")
    bin_directory = environment / "bin"
    if bin_directory.is_symlink():
        raise InstallError("The private runtime bin directory may not be a symbolic link.")
    marker = _read_owned_json(version_root / VERSION_MARKER)
    if (
        marker.get("version") != VERSION
        or marker.get("wheel_sha256") != expected_wheel_sha256
    ):
        raise InstallError(
            "The existing runtime does not match the verified release wheel; "
            "it was left inactive and unchanged."
        )
    command = environment / "bin" / "research-digest"
    if command.is_symlink() or not command.is_file() or not os.access(command, os.X_OK):
        raise InstallError("The existing versioned runtime is incomplete; it was not replaced.")
    _validate_owned_executable(command)
    resolved = command.resolve(strict=True)
    if not resolved.is_relative_to(version_root.resolve(strict=True)):
        raise InstallError("The private runtime command resolves outside its version root.")
    return resolved


def _activate_runtime(
    *,
    command: Path,
    root: Path,
    distro: str | None,
) -> dict[str, Any]:
    arguments = [
        "distribution",
        "activate",
        "--runtime-root",
        str(root),
        "--version",
        VERSION,
        "--command",
        str(command),
        "--json",
    ]
    if distro is not None:
        arguments.extend(("--distro", distro))
    payload = _run_json(command, *arguments)
    if payload.get("status") != "completed":
        raise InstallError("Private runtime activation did not complete.")
    return payload


def _prepare_owned_root(root: Path) -> None:
    if root.is_symlink():
        raise InstallError("Private runtime root may not be a symbolic link.")
    if root.exists():
        if not root.is_dir():
            raise InstallError("Private runtime root exists but is not a directory.")
        _validate_private_directory(root)
        _read_owned_json(root / ROOT_MARKER)
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    candidate = root.with_name(f".{root.name}.creating.{uuid4().hex}")
    candidate.mkdir(mode=0o700)
    try:
        _atomic_json(candidate / ROOT_MARKER, _owned_payload())
        candidate.replace(root)
    except BaseException:
        _remove_exact_root_candidate(candidate, parent=root.parent)
        raise


def _runtime_root(override: Path | None) -> Path:
    expected = (_data_dir() / "runtime").expanduser().absolute()
    if override is None:
        return expected
    requested = override.expanduser().absolute()
    if requested != expected:
        raise InstallError(f"Private runtime root must be {expected}.")
    return requested


def _data_dir() -> Path:
    override = os.environ.get("RESEARCH_DIGEST_DATA_DIR")
    if override and override.strip():
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Research Digest"
    else:
        xdg_root = os.environ.get("XDG_DATA_HOME")
        root = (
            Path(xdg_root)
            if xdg_root and xdg_root.strip()
            else Path.home() / ".local" / "share"
        )
        path = root / "research-digest"
    return path.expanduser().resolve()


def _config_dir() -> Path:
    override = os.environ.get("RESEARCH_DIGEST_CONFIG_DIR")
    if override and override.strip():
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Research Digest"
    else:
        xdg_root = os.environ.get("XDG_CONFIG_HOME")
        root = Path(xdg_root) if xdg_root and xdg_root.strip() else Path.home() / ".config"
        path = root / "research-digest"
    return path.expanduser().resolve()


def _db_path() -> Path:
    override = os.environ.get("RESEARCH_DIGEST_DB")
    if override and override.strip():
        return Path(override).expanduser().absolute()
    return _data_dir() / "research_digest.sqlite3"


def _obtain_asset(
    name: str,
    *,
    destination: Path,
    asset_dir: Path | None,
    base_url: str,
) -> Path:
    if asset_dir is not None:
        source = asset_dir.expanduser().resolve() / name
        if not source.is_file():
            raise InstallError(f"Required release asset is missing: {name}.")
        shutil.copyfile(source, destination)
        return destination
    url = f"{base_url.rstrip('/')}/{name}"
    request = urllib.request.Request(url, headers={"User-Agent": f"research-digest/{VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            allowed_redirects = (
                "https://objects.githubusercontent.com/",
                "https://release-assets.githubusercontent.com/",
            )
            if response.geturl() != url and not response.geturl().startswith(allowed_redirects):
                raise InstallError("Release asset redirected to an unexpected host.")
            with destination.open("wb") as handle:
                shutil.copyfileobj(response, handle)
    except (OSError, urllib.error.URLError) as exc:
        raise InstallError(f"Could not download exact {RELEASE_TAG} asset {name}.") from exc
    return destination


def _run_checked(executable: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [str(executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallError(f"Could not execute installation check with {executable.name}.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "no diagnostic output"
        raise InstallError(f"{executable.name} failed: {_single_line(detail)}")
    return completed


def _run_json(executable: Path, *arguments: str) -> dict[str, Any]:
    completed = _run_checked(executable, *arguments)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{executable.name} returned malformed verification JSON.") from exc
    if not isinstance(payload, dict):
        raise InstallError(f"{executable.name} returned non-object verification JSON.")
    return payload


def _remove_owned_runtime_root(root: Path) -> None:
    if root.is_symlink():
        raise InstallError("Private runtime root may not be a symbolic link.")
    _validate_private_directory(root)
    _read_owned_json(root / ROOT_MARKER)
    _validate_owned_runtime_root_contents(root)
    shutil.rmtree(root)


def _validate_owned_runtime_root_contents(root: Path) -> None:
    allowed_files = {ROOT_MARKER, CURRENT_STATE, PREVIOUS_STATE}
    for entry in root.iterdir():
        if entry.name in allowed_files:
            if entry.is_symlink() or not entry.is_file():
                raise InstallError(
                    f"Unexpected runtime state entry prevents removal: {entry.name}."
                )
            payload = _read_owned_json(entry)
            if entry.name in {CURRENT_STATE, PREVIOUS_STATE}:
                _validate_runtime_record_payload(payload, root=root, path=entry)
            continue
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or VERSION_PATTERN.fullmatch(entry.name) is None
        ):
            raise InstallError(f"Unowned runtime entry prevents removal: {entry.name}.")
        _validate_private_directory(entry)
        marker = _read_owned_json(entry / VERSION_MARKER)
        if marker.get("version") != entry.name:
            raise InstallError(
                f"Runtime marker does not match version directory: {entry.name}."
            )


def _validate_runtime_record_payload(
    payload: dict[str, Any],
    *,
    root: Path,
    path: Path,
) -> None:
    version = payload.get("version")
    command = payload.get("command")
    if (
        not isinstance(version, str)
        or VERSION_PATTERN.fullmatch(version) is None
        or not isinstance(command, str)
    ):
        raise InstallError(f"Runtime state record is incomplete: {path}.")
    expected = root / version / "venv" / "bin" / "research-digest"
    if Path(command) != expected:
        raise InstallError(f"Runtime state record points outside its version: {path}.")


def _remove_exact_version_under_construction(version_root: Path, *, root: Path) -> None:
    if (
        version_root.parent != root
        or version_root.name != VERSION
        or version_root.is_symlink()
    ):
        raise InstallError("Refusing unsafe versioned-runtime cleanup.")
    if version_root.exists():
        shutil.rmtree(version_root)


def _remove_exact_root_candidate(candidate: Path, *, parent: Path) -> None:
    if (
        candidate.parent != parent
        or not candidate.name.startswith(".runtime.creating.")
        or candidate.is_symlink()
    ):
        raise InstallError("Refusing unsafe runtime-root cleanup.")
    if candidate.exists():
        shutil.rmtree(candidate)


def _build_purge_plan() -> PurgePlan:
    directories = {_purge_path("RESEARCH_DIGEST_DATA_DIR", _data_dir())}
    directories.add(_purge_path("RESEARCH_DIGEST_CONFIG_DIR", _config_dir()))
    for path in directories:
        resolved = path.resolve()
        if resolved in {Path("/"), Path.home().resolve()} or resolved.name not in {
            "Research Digest",
            "research-digest",
        }:
            raise InstallError(f"Refusing to purge a broad or non-application path: {path}.")
        if path.is_symlink():
            raise InstallError(f"Refusing to purge symbolic-link data path: {path}.")
        if path.exists() and not path.is_dir():
            raise InstallError(f"Refusing to purge non-directory application path: {path}.")

    database = _purge_path("RESEARCH_DIGEST_DB", _db_path())
    if database.is_symlink():
        raise InstallError(f"Refusing to purge symbolic-link database path: {database}.")
    resolved_directories = tuple(path.resolve() for path in directories)
    database_covered = any(
        database.resolve() == directory or database.resolve().is_relative_to(directory)
        for directory in resolved_directories
    )
    files: list[Path] = []
    if not database_covered:
        for path in (
            database,
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
            database.with_name(database.name + "-journal"),
        ):
            if not path.exists():
                continue
            if path.is_symlink():
                raise InstallError(f"Refusing to purge symbolic-link database path: {path}.")
            metadata = path.stat()
            if not path.is_file() or metadata.st_uid != os.getuid():
                raise InstallError(f"Refusing to purge an unowned database file: {path}.")
            resolved = path.resolve()
            if resolved in {Path("/"), Path.home().resolve()}:
                raise InstallError(f"Refusing to purge a broad database path: {path}.")
            files.append(path)
    return PurgePlan(
        directories=tuple(sorted(directories, key=os.fspath)),
        files=tuple(files),
    )


def _purge_personal_data(plan: PurgePlan) -> None:
    for path in plan.files:
        path.unlink(missing_ok=True)
    for path in plan.directories:
        if path.exists():
            shutil.rmtree(path)


def _purge_path(environment_name: str, default: Path) -> Path:
    override = os.environ.get(environment_name)
    if override and override.strip():
        return Path(override).expanduser().absolute()
    return default


def _read_owned_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise InstallError(f"Owned state may not be a symbolic link: {path}.")
    _validate_private_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"Owned runtime state is missing or invalid: {path}.") from exc
    if not isinstance(payload, dict):
        raise InstallError(f"Owned runtime state is not an object: {path}.")
    if payload.get("owner") != OWNER or payload.get("schema_version") != STATE_SCHEMA:
        raise InstallError(f"Runtime state is not owned by Research Digest: {path}.")
    return payload


def _read_optional_owned_json(path: Path) -> dict[str, Any] | None:
    return _read_owned_json(path) if path.exists() else None


def _command_from_state(payload: dict[str, Any] | None) -> Path | None:
    if payload is None:
        return None
    command = payload.get("command")
    version = payload.get("version")
    if (
        not isinstance(command, str)
        or not Path(command).is_absolute()
        or not isinstance(version, str)
        or VERSION_PATTERN.fullmatch(version) is None
    ):
        raise InstallError("Current runtime state is incomplete.")
    version_root = _runtime_root(None) / version
    environment = version_root / "venv"
    bin_directory = environment / "bin"
    expected = bin_directory / "research-digest"
    command_path = Path(command)
    if (
        version_root.is_symlink()
        or environment.is_symlink()
        or bin_directory.is_symlink()
        or expected.is_symlink()
        or command_path.is_symlink()
        or command_path != expected
    ):
        raise InstallError("Current runtime command is outside the owned runtime.")
    _validate_private_directory(version_root)
    marker = _read_owned_json(version_root / VERSION_MARKER)
    marker_hash = marker.get("wheel_sha256")
    if (
        marker.get("version") != version
        or not isinstance(marker_hash, str)
        or SHA256_DIGEST_PATTERN.fullmatch(marker_hash) is None
    ):
        raise InstallError("Current runtime version marker does not match its directory.")
    resolved = command_path.resolve(strict=True)
    if (
        resolved != expected.resolve(strict=True)
        or not resolved.is_relative_to(version_root.resolve(strict=True))
        or not os.access(resolved, os.X_OK)
    ):
        raise InstallError("Current runtime command is outside the owned runtime.")
    _validate_owned_executable(resolved)
    return resolved


def _validate_private_directory(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise InstallError(f"Owned runtime directory is unavailable: {path}.") from exc
    if not path.is_dir() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise InstallError(
            f"Owned runtime directory must belong to the current user with mode 0700: {path}."
        )


def _validate_private_file(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise InstallError(f"Owned runtime state is missing or invalid: {path}.") from exc
    if not path.is_file() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise InstallError(
            f"Owned runtime state must belong to the current user with mode 0600: {path}."
        )


def _validate_owned_executable(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise InstallError(f"Owned runtime command is unavailable: {path}.") from exc
    if (
        not path.is_file()
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o022
        or not os.access(path, os.X_OK)
    ):
        raise InstallError(
            "Owned runtime command must belong to the current user, be executable, "
            f"and not be group/other writable: {path}."
        )


def _owned_payload(
    *,
    version: str | None = None,
    command: str | None = None,
    wheel_sha256: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"schema_version": STATE_SCHEMA, "owner": OWNER}
    if version is not None:
        payload["version"] = version
    if command is not None:
        payload["command"] = command
    if wheel_sha256 is not None:
        if SHA256_DIGEST_PATTERN.fullmatch(wheel_sha256) is None:
            raise InstallError("Wheel SHA-256 ownership metadata is invalid.")
        payload["wheel_sha256"] = wheel_sha256
    return payload


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    if path.is_symlink():
        raise InstallError(f"Refusing to replace symbolic-link state: {path}.")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _require_supported_python() -> None:
    if sys.version_info < (3, 11):  # noqa: UP036 - standalone script may run on old Python
        raise InstallError("Python 3.11 or newer is required; no runtime was created.")


def _require_supported_platform() -> None:
    if sys.platform == "darwin":
        return
    if sys.platform.startswith("linux") and os.environ.get("WSL_DISTRO_NAME"):
        return
    raise InstallError("This installer supports macOS and Windows 11 through WSL2.")


def _single_line(value: str) -> str:
    return " ".join(value.split())[:500]


def _print_install_result(result: dict[str, object]) -> None:
    print("Research Digest installation completed.")
    print(f"Research Digest now runs from:\n  {result['command']}")
    if result.get("reused"):
        print("The already-qualified runtime was verified and reused.")
    print("Open Research Digest.app on macOS or the Research Digest Desktop shortcut.")
    print(
        "An old source checkout is no longer required for normal use and may be "
        "removed manually after verification."
    )


def _print_uninstall_result(result: dict[str, object]) -> None:
    print(result.get("message", "Research Digest application runtime was removed."))
    if result.get("data_preserved"):
        print("Personal Research Digest data and configuration were preserved.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install Research Digest from exact release assets."
    )
    parser.add_argument("--version", dest="show_version", action="store_true")
    subparsers = parser.add_subparsers(dest="action")
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--asset-dir", type=Path, help=argparse.SUPPRESS)
    install_parser.add_argument("--base-url", default=RELEASE_BASE_URL, help=argparse.SUPPRESS)
    install_parser.add_argument("--runtime-root", type=Path, help=argparse.SUPPRESS)
    install_parser.add_argument("--distro")
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument("--remove-schedule", action="store_true")
    uninstall_parser.add_argument("--purge-data", action="store_true")
    uninstall_parser.add_argument("--confirm")
    uninstall_parser.add_argument("--runtime-root", type=Path, help=argparse.SUPPRESS)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
