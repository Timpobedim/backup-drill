"""Архив копии: запись, проверка и безопасная распаковка.

Две детали, ради которых этот модуль отдельный.

Первая: архив пишется во временный файл и переносится на место одним движением. Копия, прерванная
на середине, не должна выглядеть как готовая — иначе ротация однажды удалит настоящую копию,
оставив огрызок.

Вторая: при распаковке используется фильтр `data`. Архив — это данные, которые пришли извне, и
запись вида `../../системный-файл` внутри него не должна приводить к записи за пределы папки.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from drill.manifest import Manifest

BLOCK: Final = 1024 * 1024


class ArchiveError(RuntimeError):
    """Архив не создать, не прочитать или он не тот, за кого себя выдаёт."""


@dataclass(frozen=True, slots=True)
class ArchiveInfo:
    path: Path
    size: int
    digest: str


def create(manifest: Manifest, *, roots: Mapping[str, Path], target: Path, compress: bool = True) -> ArchiveInfo:
    """Складывает файлы описи в архив. `roots` — откуда брать файлы по имени источника."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    mode = "w:gz" if compress else "w"
    try:
        with tarfile.open(tmp, mode) as archive:  # type: ignore[call-overload]
            for entry in manifest.entries:
                source = _source_path(entry.path, roots)
                archive.add(source, arcname=entry.path, recursive=False)
        os.replace(tmp, target)
    except (OSError, tarfile.TarError) as exc:
        tmp.unlink(missing_ok=True)
        raise ArchiveError(f"Не удалось создать архив {target.name}: {exc}") from exc
    return ArchiveInfo(path=target, size=target.stat().st_size, digest=digest_of(target))


def extract(path: Path, to: Path) -> int:
    """Распаковывает архив в папку. Возвращает число файлов."""
    to.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(path) as archive:
            # filter="data" запрещает выход за пределы папки, ссылки и особые файлы.
            archive.extractall(to, filter="data")
            return sum(1 for member in archive.getmembers() if member.isfile())
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError(f"Не удалось распаковать {path.name}: {exc}") from exc


def digest_of(path: Path) -> str:
    total = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(BLOCK):
                total.update(chunk)
    except OSError as exc:
        raise ArchiveError(f"Не удалось прочитать архив {path}: {exc}") from exc
    return total.hexdigest()


def same(path: Path, digest: str) -> bool:
    """Архив совпадает с тем, что записано в журнале."""
    return path.exists() and digest_of(path) == digest


def _source_path(entry_path: str, roots: Mapping[str, Path]) -> Path:
    prefix, _, rest = entry_path.partition("/")
    root = roots.get(prefix)
    if root is None:
        raise ArchiveError(f"Неизвестный источник «{prefix}» для файла {entry_path}")
    if not rest:
        return root
    return root / rest
