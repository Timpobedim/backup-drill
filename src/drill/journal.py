"""Журнал: какие копии есть, когда их проверяли восстановлением и чем это кончилось.

Без журнала «у нас есть резервные копии» — это утверждение о папке с файлами. С журналом на него
можно ответить цифрами: последняя копия такая-то, последняя успешная тревога была тогда-то.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DDL = (
    """
    CREATE TABLE IF NOT EXISTS copies (
        copy_id INTEGER PRIMARY KEY AUTOINCREMENT,
        job TEXT NOT NULL,
        created_at TEXT NOT NULL,
        path TEXT NOT NULL,
        manifest_path TEXT NOT NULL,
        size INTEGER NOT NULL,
        digest TEXT NOT NULL,
        files INTEGER NOT NULL,
        bytes_total INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS drills (
        drill_id INTEGER PRIMARY KEY AUTOINCREMENT,
        copy_id INTEGER NOT NULL,
        job TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ok INTEGER NOT NULL,
        checked INTEGER NOT NULL,
        detail TEXT NOT NULL,
        seconds REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS restores (
        restore_id INTEGER PRIMARY KEY AUTOINCREMENT,
        copy_id INTEGER NOT NULL,
        at TEXT NOT NULL,
        target TEXT NOT NULL,
        files INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS copies_job ON copies (job, created_at)",
    "CREATE INDEX IF NOT EXISTS drills_job ON drills (job, started_at)",
)


class JournalError(RuntimeError):
    """Журнал недоступен или повреждён."""


@dataclass(frozen=True, slots=True)
class Copy:
    copy_id: int
    job: str
    created_at: datetime
    path: Path
    manifest_path: Path
    size: int
    digest: str
    files: int
    bytes_total: int


@dataclass(frozen=True, slots=True)
class DrillRun:
    drill_id: int
    copy_id: int
    job: str
    started_at: datetime
    ok: bool
    checked: int
    detail: str
    seconds: float


class Journal:
    """Журнал копий и учений в одном файле SQLite."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        try:
            if str(path) != ":memory:":
                self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(path))
        except (OSError, sqlite3.Error) as exc:
            raise JournalError(f"Не удалось открыть журнал {path}: {exc}") from exc
        self.connection.row_factory = sqlite3.Row
        for statement in DDL:
            self._execute(statement)

    # ── копии ───────────────────────────────────────────────────────────────────────────────────

    def add_copy(
        self,
        *,
        job: str,
        created_at: datetime,
        path: Path,
        manifest_path: Path,
        size: int,
        digest: str,
        files: int,
        bytes_total: int,
    ) -> Copy:
        cursor = self._execute(
            "INSERT INTO copies (job, created_at, path, manifest_path, size, digest, files, bytes_total) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (job, _text(created_at), str(path), str(manifest_path), size, digest, files, bytes_total),
        )
        self.connection.commit()
        return self.copy(int(cursor.lastrowid or 0))

    def copy(self, copy_id: int) -> Copy:
        row = self._execute("SELECT * FROM copies WHERE copy_id = ?", (copy_id,)).fetchone()
        if row is None:
            raise JournalError(f"Копии №{copy_id} нет в журнале")
        return _copy(row)

    def copies(self, job: str | None = None, limit: int = 100) -> list[Copy]:
        if job:
            rows = self._execute(
                "SELECT * FROM copies WHERE job = ? ORDER BY created_at DESC, copy_id DESC LIMIT ?", (job, limit)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM copies ORDER BY created_at DESC, copy_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_copy(row) for row in rows]

    def last_copy(self, job: str) -> Copy | None:
        found = self.copies(job, limit=1)
        return found[0] if found else None

    def forget(self, copy_id: int) -> None:
        self._execute("DELETE FROM copies WHERE copy_id = ?", (copy_id,))
        self.connection.commit()

    # ── учения и восстановления ─────────────────────────────────────────────────────────────────

    def add_drill(
        self, *, copy_id: int, job: str, started_at: datetime, ok: bool, checked: int, detail: str, seconds: float
    ) -> DrillRun:
        cursor = self._execute(
            "INSERT INTO drills (copy_id, job, started_at, ok, checked, detail, seconds) VALUES (?,?,?,?,?,?,?)",
            (copy_id, job, _text(started_at), int(ok), checked, detail, round(seconds, 3)),
        )
        self.connection.commit()
        row = self._execute("SELECT * FROM drills WHERE drill_id = ?", (int(cursor.lastrowid or 0),)).fetchone()
        return _drill(row)

    def drills(self, job: str | None = None, limit: int = 20) -> list[DrillRun]:
        if job:
            rows = self._execute(
                "SELECT * FROM drills WHERE job = ? ORDER BY started_at DESC, drill_id DESC LIMIT ?", (job, limit)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM drills ORDER BY started_at DESC, drill_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_drill(row) for row in rows]

    def last_good_drill(self, job: str) -> DrillRun | None:
        row = self._execute(
            "SELECT * FROM drills WHERE job = ? AND ok = 1 ORDER BY started_at DESC, drill_id DESC LIMIT 1", (job,)
        ).fetchone()
        return _drill(row) if row is not None else None

    def add_restore(self, *, copy_id: int, at: datetime, target: Path, files: int) -> None:
        self._execute(
            "INSERT INTO restores (copy_id, at, target, files) VALUES (?,?,?,?)",
            (copy_id, _text(at), str(target), files),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        try:
            return self.connection.execute(sql, tuple(parameters))
        except sqlite3.Error as exc:
            raise JournalError(f"Запрос к журналу не выполнился: {exc}") from exc


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _moment(raw: object) -> datetime:
    return datetime.fromisoformat(str(raw))


def _copy(row: sqlite3.Row) -> Copy:
    return Copy(
        copy_id=int(row["copy_id"]),
        job=str(row["job"]),
        created_at=_moment(row["created_at"]),
        path=Path(str(row["path"])),
        manifest_path=Path(str(row["manifest_path"])),
        size=int(row["size"]),
        digest=str(row["digest"]),
        files=int(row["files"]),
        bytes_total=int(row["bytes_total"]),
    )


def _drill(row: sqlite3.Row) -> DrillRun:
    return DrillRun(
        drill_id=int(row["drill_id"]),
        copy_id=int(row["copy_id"]),
        job=str(row["job"]),
        started_at=_moment(row["started_at"]),
        ok=bool(row["ok"]),
        checked=int(row["checked"]),
        detail=str(row["detail"]),
        seconds=float(row["seconds"]),
    )
