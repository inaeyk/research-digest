from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from test_library_foundation import create_realistic_schema_18_database

from research_digest.config import CONFIG_VERSION, load_config
from research_digest.db import CURRENT_SCHEMA_VERSION, Database

INSTALLER_SPEC = importlib.util.spec_from_file_location(
    "upgrade_schema_preflight_installer",
    Path("installers/install_research_digest.py"),
)
assert INSTALLER_SPEC is not None and INSTALLER_SPEC.loader is not None
installer = importlib.util.module_from_spec(INSTALLER_SPEC)
sys.modules[INSTALLER_SPEC.name] = installer
INSTALLER_SPEC.loader.exec_module(installer)


def _write_owned(path: Path, **extra: object) -> None:
    payload = {
        "schema_version": installer.STATE_SCHEMA,
        "owner": installer.OWNER,
        **extra,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def _schema_version(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
        ).fetchone()
    assert row is not None
    return int(row[0])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UpgradeInstallerSchemaPreflightTests(unittest.TestCase):
    def test_runtime_verification_rejects_corrupt_future_and_unsupported_schema(self) -> None:
        scenarios = (
            ("corrupt", "file is not a database"),
            ("future", "newer than supported"),
            ("unsupported", "no supported migration path"),
            ("missing-metadata", "metadata is missing a supported schema version"),
        )
        for scenario, expected_error in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                test_root = Path(tmp).resolve()
                home = test_root / "home"
                data_dir = home / "data"
                config_dir = home / "config"
                db_path = data_dir / "research_digest.sqlite3"
                fake_bin = test_root / "fake-bin"
                data_dir.mkdir(parents=True)
                fake_bin.mkdir()
                if scenario == "corrupt":
                    db_path.write_bytes(b"not a SQLite database")
                elif scenario == "missing-metadata":
                    create_realistic_schema_18_database(db_path)
                    with sqlite3.connect(db_path) as conn:
                        conn.execute(
                            "DELETE FROM schema_metadata WHERE key = 'schema_version'"
                        )
                else:
                    version = "999" if scenario == "future" else "-1"
                    with sqlite3.connect(db_path) as conn:
                        conn.executescript(
                            f"""
                            CREATE TABLE schema_metadata (
                                key TEXT PRIMARY KEY,
                                value TEXT NOT NULL,
                                updated_at TEXT NOT NULL
                            );
                            INSERT INTO schema_metadata (key, value, updated_at)
                            VALUES (
                                'schema_version', '{version}', '2026-08-30T00:00:00Z'
                            );
                            """
                        )
                provider_called = test_root / "provider-was-called"
                fake_codex = fake_bin / "codex"
                fake_codex.write_text(
                    "#!/bin/sh\n: > " + shlex.quote(str(provider_called)) + "\nexit 97\n",
                    encoding="utf-8",
                )
                fake_codex.chmod(0o755)
                environment = {
                    "HOME": str(home),
                    "PATH": str(fake_bin),
                    "WSL_DISTRO_NAME": "Research Debian",
                    "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                    "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                    "RESEARCH_DIGEST_DB": str(db_path),
                }
                with mock.patch.dict(os.environ, environment, clear=True):
                    load_config()
                before = db_path.read_bytes()

                with (
                    mock.patch.dict(os.environ, environment, clear=True),
                    self.assertRaisesRegex(installer.InstallError, expected_error),
                ):
                    installer.verify_runtime(Path(".venv/bin/research-digest").resolve())

                self.assertEqual(db_path.read_bytes(), before)
                self.assertEqual(list(data_dir.glob("*.backup-v*-to-v*-*.sqlite3")), [])
                self.assertFalse(provider_called.exists())

    def test_schema_18_install_is_immutable_then_first_startup_migrates_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            test_root = Path(tmp).resolve()
            home = test_root / "home"
            data_dir = home / "data"
            config_dir = home / "config"
            db_path = data_dir / "research_digest.sqlite3"
            fake_bin = test_root / "fake-bin"
            home.mkdir()
            data_dir.mkdir(parents=True)
            fake_bin.mkdir()

            create_realistic_schema_18_database(db_path)
            provider_called = test_root / "provider-was-called"
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                "#!/bin/sh\n: > " + shlex.quote(str(provider_called)) + "\nexit 97\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            environment = {
                "HOME": str(home),
                "PATH": str(fake_bin),
                "WSL_DISTRO_NAME": "Research Debian",
                "RESEARCH_DIGEST_DATA_DIR": str(data_dir),
                "RESEARCH_DIGEST_CONFIG_DIR": str(config_dir),
                "RESEARCH_DIGEST_DB": str(db_path),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                config = load_config()
            self.assertEqual(config.config_version, CONFIG_VERSION)
            assert config.config_path is not None

            runtime_root = data_dir / "runtime"
            old_version_root = runtime_root / "0.4.1"
            old_command = old_version_root / "venv" / "bin" / "research-digest"
            old_command.parent.mkdir(parents=True)
            runtime_root.chmod(0o700)
            old_version_root.chmod(0o700)
            old_command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            old_command.chmod(0o755)
            _write_owned(runtime_root / installer.ROOT_MARKER)
            _write_owned(
                old_version_root / installer.VERSION_MARKER,
                version="0.4.1",
                wheel_sha256="1" * 64,
            )
            _write_owned(
                runtime_root / installer.CURRENT_STATE,
                version="0.4.1",
                command=str(old_command),
            )

            assets = test_root / "assets"
            assets.mkdir()
            wheel = assets / installer.WHEEL_NAME
            wheel.write_bytes(b"deterministic candidate wheel fixture")
            wheel_hash = _sha256(wheel)
            (assets / installer.MANIFEST_NAME).write_text(
                f"{wheel_hash}  {installer.WHEEL_NAME}\n",
                encoding="ascii",
            )
            real_cli = Path(".venv/bin/research-digest").resolve()
            config_before = config.config_path.read_bytes()
            db_hash_before = _sha256(db_path)

            def create_candidate(
                *, root: Path, wheel_path: Path, wheel_sha256: str
            ) -> Path:
                self.assertEqual(_sha256(wheel_path), wheel_sha256)
                version_root = root / installer.VERSION
                command = version_root / "venv" / "bin" / "research-digest"
                command.parent.mkdir(parents=True)
                version_root.chmod(0o700)
                command.write_text(
                    "#!/bin/sh\nexec " + shlex.quote(str(real_cli)) + ' "$@"\n',
                    encoding="utf-8",
                )
                command.chmod(0o755)
                installer.verify_runtime(command.resolve())
                _write_owned(
                    version_root / installer.VERSION_MARKER,
                    version=installer.VERSION,
                    wheel_sha256=wheel_sha256,
                )
                return cast(Path, command.resolve())

            verification: Any

            def activate_candidate(*, command: Path, root: Path, distro: str | None) -> object:
                del distro
                self.assertEqual(verification.call_count, 2)
                current = json.loads((root / installer.CURRENT_STATE).read_text(encoding="utf-8"))
                self.assertEqual(current["version"], "0.4.1")
                _write_owned(
                    root / installer.CURRENT_STATE,
                    version=installer.VERSION,
                    command=str(command),
                )
                return {"status": "completed", "schedule_migrated": False}

            with (
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(installer.sys, "platform", "linux"),
                mock.patch.object(
                    installer,
                    "_create_versioned_runtime",
                    side_effect=create_candidate,
                ),
                mock.patch.object(
                    installer,
                    "verify_runtime",
                    wraps=installer.verify_runtime,
                ) as verification,
                mock.patch.object(
                    installer,
                    "_activate_runtime",
                    side_effect=activate_candidate,
                ),
            ):
                result = installer.install(
                    asset_dir=assets,
                    distro="Research Debian",
                    runtime_root=runtime_root,
                )

            self.assertEqual(result["version"], "0.5.0")
            self.assertEqual(verification.call_count, 2)
            self.assertEqual(_sha256(db_path), db_hash_before)
            self.assertEqual(config.config_path.read_bytes(), config_before)
            self.assertEqual(_schema_version(db_path), 18)
            self.assertEqual(
                list(data_dir.glob("research_digest.sqlite3.backup-v18-to-v20-*.sqlite3")),
                [],
            )
            self.assertFalse(provider_called.exists())
            current = json.loads(
                (runtime_root / installer.CURRENT_STATE).read_text(encoding="utf-8")
            )
            self.assertEqual(current["version"], "0.5.0")
            self.assertTrue((runtime_root / "0.5.0").is_dir())

            forbidden = AssertionError("normal startup migration crossed an external boundary")
            with (
                mock.patch(
                    "research_digest.analysis.providers.build_configured_analyzer",
                    side_effect=forbidden,
                ) as analyzer_factory,
                mock.patch(
                    "research_digest.analysis.openai.OpenAIAnalyzer.analyze_many",
                    side_effect=forbidden,
                ) as openai_analyze,
                mock.patch(
                    "research_digest.analysis.codex_cli.CodexCLIAnalyzer.analyze_many",
                    side_effect=forbidden,
                ) as codex_analyze,
                mock.patch("subprocess.Popen", side_effect=forbidden) as process_start,
                mock.patch("urllib.request.urlopen", side_effect=forbidden) as network_call,
            ):
                migrated = Database(db_path)
            analyzer_factory.assert_not_called()
            openai_analyze.assert_not_called()
            codex_analyze.assert_not_called()
            process_start.assert_not_called()
            network_call.assert_not_called()
            self.assertEqual(migrated.get_schema_version(), CURRENT_SCHEMA_VERSION)

            backups = list(
                data_dir.glob("research_digest.sqlite3.backup-v18-to-v20-*.sqlite3")
            )
            self.assertEqual(len(backups), 1)
            self.assertEqual(migrated.last_migration_backup_path, backups[0])
            with sqlite3.connect(backups[0]) as backup:
                self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(backup.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    backup.execute(
                        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
                    ).fetchone(),
                    ("18",),
                )
            with sqlite3.connect(db_path) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone(), (1,))
                self.assertEqual(
                    conn.execute(
                        "SELECT interest_rating, reading_state FROM library_articles"
                    ).fetchone(),
                    (None, None),
                )
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_artifacts").fetchone(), (0,))
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM relevance_analyses "
                        "WHERE summary_artifact_id IS NOT NULL"
                    ).fetchone(),
                    (0,),
                )

            reopened = Database(db_path)
            self.assertEqual(reopened.get_schema_version(), CURRENT_SCHEMA_VERSION)
            self.assertIsNone(reopened.last_migration_backup_path)
            self.assertEqual(
                list(data_dir.glob("research_digest.sqlite3.backup-v18-to-v20-*.sqlite3")),
                backups,
            )
            self.assertFalse(provider_called.exists())


if __name__ == "__main__":
    unittest.main()
