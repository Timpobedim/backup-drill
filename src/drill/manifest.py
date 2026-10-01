"""Опись копии: какие файлы вошли, какого размера и с какой контрольной суммой.

Опись — это то, что превращает «архив вроде бы создался» в проверяемое утверждение. Без неё
восстановление можно только посмотреть глазами; с ней — сверить каждый файл побайтово.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

BLOCK: Final = 1024 * 1024


class ManifestError(RuntimeError):
    """Не удалось собрать опись: недоступен источник или файл."""


@dataclass(frozen=True, slots=True)
class Entry:
    """Один файл в копии."""

    path: str
    size: int
    digest: str
    modified: float

    def as_dict(self) -> dict[str, Any]:
        return {"путь": self.path, "размер": self.size, "сумма": self.digest, "изменён": self.modified}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Entry:
        return cls(
            path=str(raw["путь"]),
            size=int(raw["размер"]),
            digest=str(raw["сумма"]),
            modified=float(raw["изменён"]),
        )


@dataclass(frozen=True, slots=True)
class Difference:
    """Чем восстановленное отличается от записанного."""

    missing: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.missing or self.changed or self.extra)

    def line(self) -> str:
        if self.ok:
            return "все файлы совпали"
        parts = []
        if self.missing:
            parts.append(f"не хватает {len(self.missing)}")
        if self.changed:
            parts.append(f"изменилось {len(self.changed)}")
        if self.extra:
            parts.append(f"лишних {len(self.extra)}")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class Manifest:
    job: str
    created_at: datetime
    entries: tuple[Entry, ...]

    @property
    def files(self) -> int:
        return len(self.entries)

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries)

    def to_json(self) -> str:
        payload = {
            "задание": self.job,
            "собрана": self.created_at.astimezone(UTC).isoformat(),
            "файлы": [entry.as_dict() for entry in self.entries],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        try:
            raw = json.loads(text)
            return cls(
                job=str(raw["задание"]),
                created_at=datetime.fromisoformat(str(raw["собрана"])),
                entries=tuple(Entry.from_dict(item) for item in raw["файлы"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"Опись повреждена: {exc}") from exc

    def compare(self, other: Manifest) -> Difference:
        """Сравнивает эту опись с описью восстановленного."""
        mine = {entry.path: entry for entry in self.entries}
        theirs = {entry.path: entry for entry in other.entries}
        missing = tuple(sorted(set(mine) - set(theirs)))
        extra = tuple(sorted(set(theirs) - set(mine)))
        changed = tuple(sorted(path for path in set(mine) & set(theirs) if mine[path].digest != theirs[path].digest))
        return Difference(missing=missing, changed=changed, extra=extra)


def digest_of(path: Path) -> str:
    """Контрольная сумма файла, считанная блоками: файл может быть больше памяти."""
    total = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(BLOCK):
                total.update(chunk)
    except OSError as exc:
        raise ManifestError(f"Не удалось прочитать {path}: {exc}") from exc
    return total.hexdigest()


def excluded(relative: str, name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def collect(
    job_name: str, sources: Iterable[Path], *, excludes: Sequence[str] = (), now: datetime | None = None
) -> Manifest:
    """Обходит источники и считает опись. Пути в копии начинаются с имени источника."""
    entries: list[Entry] = []
    for source in sources:
        if not source.exists():
            raise ManifestError(f"Источник не найден: {source}")
        prefix = source.name
        if source.is_file():
            entries.append(_entry(source, prefix, excludes))
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            relative = f"{prefix}/{path.relative_to(source).as_posix()}"
            if excluded(relative, path.name, excludes):
                continue
            entries.append(
                Entry(path=relative, size=path.stat().st_size, digest=digest_of(path), modified=path.stat().st_mtime)
            )
    return Manifest(
        job=job_name, created_at=now or datetime.now(UTC), entries=tuple(sorted(entries, key=lambda item: item.path))
    )


def scan(folder: Path, job_name: str = "восстановленное", *, now: datetime | None = None) -> Manifest:
    """Опись уже разложенной на диске копии — по ней сверяется восстановление."""
    entries = [
        Entry(
            path=path.relative_to(folder).as_posix(),
            size=path.stat().st_size,
            digest=digest_of(path),
            modified=path.stat().st_mtime,
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    ]
    return Manifest(job=job_name, created_at=now or datetime.now(UTC), entries=tuple(entries))


def _entry(path: Path, prefix: str, excludes: Sequence[str]) -> Entry:
    if excluded(prefix, path.name, excludes):
        raise ManifestError(f"Источник {path} сам попадает под исключения — проверьте настройки")
    stat = path.stat()
    return Entry(path=prefix, size=stat.st_size, digest=digest_of(path), modified=stat.st_mtime)
