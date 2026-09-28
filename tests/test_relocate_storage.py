import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "relocate_storage", Path(__file__).resolve().parents[1] / "scripts/relocate_storage.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def prepare(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    new.mkdir()
    database = tmp_path / "copy.sqlite3"
    with sqlite3.connect(database) as c:
        c.execute(
            "CREATE TABLE recognition_jobs (id TEXT, original_path TEXT, original_sha256 TEXT)"
        )
        c.execute(
            "CREATE TABLE recognition_attempts (id TEXT, status TEXT, processed_path TEXT, processed_sha256 TEXT)"
        )
        c.execute("CREATE TABLE dataset_versions (id TEXT, directory TEXT, manifest_sha256 TEXT)")
        for name in ("first.jpg", "second.jpg"):
            payload = name.encode()
            (new / name).write_bytes(payload)
            c.execute(
                "INSERT INTO recognition_jobs VALUES (?, ?, ?)",
                (name, str(old / name), hashlib.sha256(payload).hexdigest()),
            )
    return database, old, new


def test_relocate_checks_hash_and_is_idempotent(tmp_path):
    database, old, new = prepare(tmp_path)
    assert module.relocate(database, old, new)["original_path"] == 2
    assert module.relocate(database, old, new)["original_path"] == 0
    with sqlite3.connect(database) as c:
        assert all(
            Path(row[0]).parent == new
            for row in c.execute("SELECT original_path FROM recognition_jobs")
        )


def test_mismatch_rolls_back_all_paths(tmp_path):
    database, old, new = prepare(tmp_path)
    (new / "second.jpg").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        module.relocate(database, old, new)
    with sqlite3.connect(database) as c:
        assert all(
            Path(row[0]).parent == old
            for row in c.execute("SELECT original_path FROM recognition_jobs")
        )


def test_active_jobs_prevent_relocation(tmp_path):
    database, old, new = prepare(tmp_path)
    with sqlite3.connect(database) as c:
        c.execute("INSERT INTO recognition_attempts VALUES ('a', 'RUNNING', NULL, NULL)")
    with pytest.raises(ValueError, match="Active recognition"):
        module.relocate(database, old, new)
