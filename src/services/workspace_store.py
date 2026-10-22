"""Project-local SQLite persistence and capability-based workspace ownership.

An opaque 256-bit key authenticates an owner. Only its SHA-256 digest is stored;
no key appears in URLs. Every data query is scoped by the authenticated workspace.
"""

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = 2
MAX_WORKSPACES = 100
MAX_WORKSPACE_BYTES = 8 * 1024 * 1024
MAX_HISTORY = 10
MIGRATIONS = {
    1: [
        "CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "owner_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, revision INTEGER NOT NULL "
        "DEFAULT 0, datasets TEXT)",
        "CREATE TABLE analyses (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL "
        "REFERENCES workspaces(id) ON DELETE CASCADE, revision INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, result TEXT NOT NULL)",
        "CREATE INDEX analysis_owner ON analyses(workspace_id, created_at)",
    ],
    2: [
        "ALTER TABLE workspaces ADD COLUMN expires_at TEXT",
        "CREATE INDEX workspace_expiry ON workspaces(expires_at)",
    ],
}


class StoreError(RuntimeError):
    pass


class CapacityError(StoreError):
    pass


class RevisionConflict(StoreError):
    pass


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def now() -> str:
    return datetime.now(UTC).isoformat()


class WorkspaceStore:
    def __init__(self, path: Path):
        self.path = path
        self.ttl_hours = int(os.environ.get("WORKSPACE_TTL_HOURS", "0"))
        if not 0 <= self.ttl_hours <= 168:
            raise ValueError("WORKSPACE_TTL_HOURS musi być w zakresie 0–168")

    @contextmanager
    def connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            if write:
                connection.execute("PRAGMA max_page_count=65536")
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        self.path.chmod(0o600)
        with self.connection(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StoreError("Baza ma nowszy schemat niż aplikacja; uruchom właściwe wydanie")
            for target in range(version + 1, SCHEMA_VERSION + 1):
                for statement in MIGRATIONS[target]:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version={target}")

    def ready(self):
        with self.connection() as connection:
            connection.execute("SELECT id FROM workspaces LIMIT 1")
            connection.execute("SELECT id FROM analyses LIMIT 1")
            return connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    def cleanup_expired(self):
        with self.connection(write=True) as connection:
            count = connection.execute(
                "DELETE FROM workspaces WHERE expires_at IS NOT NULL AND expires_at<=?", (now(),)
            ).rowcount
        return count

    def create(self, name: str) -> dict:
        key = secrets.token_urlsafe(32)
        workspace_id = secrets.token_hex(16)
        created_at = now()
        expires_at = (
            (datetime.now(UTC) + timedelta(hours=self.ttl_hours)).isoformat()
            if self.ttl_hours
            else None
        )
        with self.connection(write=True) as connection:
            connection.execute(
                "DELETE FROM workspaces WHERE expires_at IS NOT NULL AND expires_at<=?",
                (created_at,),
            )
            if (
                connection.execute("SELECT count(*) FROM workspaces").fetchone()[0]
                >= MAX_WORKSPACES
            ):
                raise CapacityError(
                    f"Limit {MAX_WORKSPACES} przestrzeni osiągnięty; "
                    "spróbuj po wygaśnięciu starszych danych"
                )
            connection.execute(
                "INSERT INTO workspaces(id,name,owner_hash,created_at,expires_at) "
                "VALUES(?,?,?,?,?)",
                (
                    workspace_id,
                    name,
                    hashlib.sha256(key.encode()).hexdigest(),
                    created_at,
                    expires_at,
                ),
            )
        return {"id": workspace_id, "name": name, "key": key, "created_at": created_at}

    def authenticate(self, workspace_id: str, key: str) -> bool:
        digest = hashlib.sha256(key.encode()).hexdigest()
        with self.connection() as connection:
            row = connection.execute(
                "SELECT owner_hash FROM workspaces WHERE id=? "
                "AND (expires_at IS NULL OR expires_at>?)",
                (workspace_id, now()),
            ).fetchone()
        return secrets.compare_digest(digest, row[0] if row else "0" * 64) and row is not None

    def get(self, workspace_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT id,name,revision,created_at,datasets FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise StoreError("Przestrzeń nie istnieje")
        result = dict(row)
        result["datasets"] = json.loads(row["datasets"]) if row["datasets"] else None
        return result

    def replace_datasets(self, workspace_id: str, revision: int, datasets: dict) -> dict:
        payload = encode(datasets)
        with self.connection(write=True) as connection:
            current = connection.execute(
                "SELECT revision FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
            if current is None or current[0] != revision:
                raise RevisionConflict("Dane zmieniły się. Odczytaj przestrzeń i ponów zapis")
            used = connection.execute(
                "SELECT coalesce(sum(length(CAST(result AS BLOB))),0) FROM analyses "
                "WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()[0]
            if used + len(payload.encode()) > MAX_WORKSPACE_BYTES:
                raise CapacityError("Limit przestrzeni 8 MiB; usuń starsze analizy i ponów zapis")
            connection.execute(
                "UPDATE workspaces SET datasets=?, revision=revision+1 WHERE id=?",
                (payload, workspace_id),
            )
        return self.get(workspace_id)

    def save_analysis(self, workspace_id: str, revision: int, result: dict) -> dict:
        analysis_id = secrets.token_hex(16)
        result = {**result, "analysis_id": analysis_id, "revision": revision, "created_at": now()}
        payload = encode(result)
        with self.connection(write=True) as connection:
            row = connection.execute(
                "SELECT revision,length(CAST(datasets AS BLOB)) FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
            if row is None or row[0] != revision:
                raise RevisionConflict("Dane zmieniły się w trakcie obliczeń. Ponów analizę")
            history = connection.execute(
                "SELECT id,length(CAST(result AS BLOB)) FROM analyses WHERE workspace_id=? "
                "ORDER BY created_at DESC,id DESC",
                (workspace_id,),
            ).fetchall()
            used = (row[1] or 0) + len(payload.encode())
            if used > MAX_WORKSPACE_BYTES:
                raise CapacityError("Wynik przekracza limit przestrzeni 8 MiB")
            keep = 0
            for previous in history:
                if keep < MAX_HISTORY - 1 and used + previous[1] <= MAX_WORKSPACE_BYTES:
                    keep += 1
                    used += previous[1]
                else:
                    connection.execute("DELETE FROM analyses WHERE id=?", (previous[0],))
            connection.execute(
                "INSERT INTO analyses VALUES(?,?,?,?,?)",
                (analysis_id, workspace_id, revision, result["created_at"], payload),
            )
        return result

    def history(self, workspace_id: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id,revision,created_at,json_extract(result,'$.status') AS status "
                "FROM analyses WHERE workspace_id=? ORDER BY created_at DESC,id DESC",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def analysis(self, workspace_id: str, analysis_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT result FROM analyses WHERE workspace_id=? AND id=?",
                (workspace_id, analysis_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def delete_analysis(self, workspace_id: str, analysis_id: str):
        with self.connection(write=True) as connection:
            connection.execute(
                "DELETE FROM analyses WHERE workspace_id=? AND id=?", (workspace_id, analysis_id)
            )

    def delete(self, workspace_id: str):
        with self.connection(write=True) as connection:
            connection.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))

    def rotate_key(self, workspace_id: str) -> str:
        key = secrets.token_urlsafe(32)
        with self.connection(write=True) as connection:
            connection.execute(
                "UPDATE workspaces SET owner_hash=? WHERE id=?",
                (hashlib.sha256(key.encode()).hexdigest(), workspace_id),
            )
        return key

    def inventory(self):
        with self.connection() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id,name,created_at,revision FROM workspaces ORDER BY created_at"
                )
            ]

    def backup(self, destination: Path):
        if not self.path.is_file():
            raise StoreError("Baza źródłowa nie istnieje")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with destination.open("xb"):
            pass
        destination.chmod(0o600)
        with self.connection() as source, sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise StoreError("Backup nie przeszedł integrity_check")
