"""Offline backup/restore. Never truncates or replaces an existing database."""

import argparse
import json
import sqlite3
from pathlib import Path

from src.services.workspace_store import SCHEMA_VERSION, StoreError, WorkspaceStore


def restore(source: Path, destination: Path):
    if destination.exists() or any(
        Path(str(destination) + suffix).exists() for suffix in ("-wal", "-shm")
    ):
        raise StoreError("Odtwarzaj do nowego pliku; istniejący magazyn pozostaje nienaruszony")
    if not source.is_file():
        raise StoreError("Brak pliku backupu")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as backup:
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise StoreError("Backup jest uszkodzony")
        if backup.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise StoreError("Nieobsługiwana wersja backupu")
        if backup.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise StoreError("Backup zawiera nieprawidłowe relacje")
        tables = {
            row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"workspaces", "analyses"}.issubset(tables):
            raise StoreError("Backup nie zawiera wymaganych tabel")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
        destination.chmod(0o600)
        with sqlite3.connect(destination) as target:
            backup.backup(target)
    WorkspaceStore(destination).initialize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    backup = subcommands.add_parser("backup")
    backup.add_argument("--database", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    recovery = subcommands.add_parser("restore")
    recovery.add_argument("--source", type=Path, required=True)
    recovery.add_argument("--destination", type=Path, required=True)
    inventory = subcommands.add_parser("list-workspaces")
    inventory.add_argument("--database", type=Path, required=True)
    remove = subcommands.add_parser("delete-workspace")
    remove.add_argument("--database", type=Path, required=True)
    remove.add_argument("--workspace-id", required=True)
    remove.add_argument("--confirm-id", required=True)
    args = parser.parse_args()
    if args.command == "backup":
        if not args.database.is_file():
            parser.error("Baza źródłowa nie istnieje")
        WorkspaceStore(args.database).backup(args.output)
    elif args.command == "restore":
        restore(args.source, args.destination)
    else:
        if not args.database.is_file():
            parser.error("Baza źródłowa nie istnieje")
        repository = WorkspaceStore(args.database)
        if args.command == "list-workspaces":
            print(json.dumps(repository.inventory(), ensure_ascii=True, indent=2))
            return
        if args.workspace_id != args.confirm_id:
            parser.error("--confirm-id musi odpowiadać usuwanej przestrzeni")
        repository.delete(args.workspace_id)
        print("Usunięto wyłącznie wskazaną przestrzeń")
        return
    print("OK: backup/restore zweryfikowany przez SQLite integrity_check")


if __name__ == "__main__":
    main()
