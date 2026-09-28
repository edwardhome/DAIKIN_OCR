"""Rebase a stopped deployment's storage paths after copying its files and database."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def relocate(database, old_root, new_root):
    old_root, new_root = Path(old_root).resolve(), Path(new_root).resolve()
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=rw", uri=True)
    changes = {}
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                "SELECT count(*) FROM recognition_attempts "
                "WHERE status IN ('QUEUED', 'PREPROCESSING', 'RUNNING')"
            ).fetchone()[0]
            if active:
                raise ValueError("Active recognition jobs exist; stop and drain before relocating.")
            for table, column, hash_column, is_directory in (
                ("recognition_jobs", "original_path", "original_sha256", False),
                ("recognition_attempts", "processed_path", "processed_sha256", False),
                ("dataset_versions", "directory", "manifest_sha256", True),
            ):
                changes[column] = 0
                for identifier, current, expected_hash in connection.execute(
                    f"SELECT id, {column}, {hash_column} FROM {table} WHERE {column} IS NOT NULL"
                ).fetchall():
                    original = Path(current)
                    if original.is_relative_to(new_root):
                        destination = original
                    else:
                        destination = new_root / original.relative_to(old_root)
                    resolved = destination.resolve()
                    if not resolved.is_relative_to(new_root):
                        raise ValueError("Storage path escapes the destination root.")
                    evidence = resolved / "manifest.json" if is_directory else resolved
                    if (
                        not expected_hash
                        or hashlib.sha256(evidence.read_bytes()).hexdigest() != expected_hash
                    ):
                        raise ValueError(f"Copied storage hash mismatch: {table}/{identifier}")
                    if current != str(destination):
                        connection.execute(
                            f"UPDATE {table} SET {column}=? WHERE id=?",
                            (str(destination), identifier),
                        )
                        changes[column] += 1
    finally:
        connection.close()
    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--old-root", required=True)
    parser.add_argument("--new-root", required=True)
    args = parser.parse_args()
    print(json.dumps(relocate(args.database, args.old_root, args.new_root)))
