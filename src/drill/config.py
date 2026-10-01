"""Настройки: что копировать, куда, сколько хранить и как часто проверять восстановление.

Один TOML-файл вместо набора скриптов с путями внутри. Проверка настроек строгая и на месте: лучше
получить понятную ошибку при запуске, чем узнать о неверном пути в три часа ночи из письма планировщика.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

DEFAULT_KEEP_DAILY: Final = 7
DEFAULT_KEEP_WEEKLY: Final = 4
DEFAULT_KEEP_MONTHLY: Final = 6
DEFAULT_DRILL_DAYS: Final = 7.0


class ConfigError(ValueError):
    """Файл настроек написан неправильно; текст — для человека."""


@dataclass(frozen=True, slots=True)
class Job:
    """Одно задание: набор источников и правила хранения копий."""

    name: str
    sources: tuple[Path, ...]
    excludes: tuple[str, ...] = ()
    compress: bool = True
    keep_daily: int = DEFAULT_KEEP_DAILY
    keep_weekly: int = DEFAULT_KEEP_WEEKLY
    keep_monthly: int = DEFAULT_KEEP_MONTHLY

    @property
    def suffix(self) -> str:
        return ".tar.gz" if self.compress else ".tar"


@dataclass(frozen=True, slots=True)
class Settings:
    folder: Path
    journal: Path
    jobs: tuple[Job, ...]
    drill_every_days: float = DEFAULT_DRILL_DAYS

    def job(self, name: str) -> Job | None:
        return next((item for item in self.jobs if item.name == name), None)


def parse(data: dict[str, Any], base: Path = Path()) -> Settings:
    """Разбирает уже прочитанный TOML."""
    storage = data.get("storage", {})
    if not isinstance(storage, dict):
        raise ConfigError("Секция [storage] — это таблица настроек")
    jobs_raw = data.get("job")
    if not isinstance(jobs_raw, list) or not jobs_raw:
        raise ConfigError("Нужно хотя бы одно задание: секция [[job]]")

    jobs = tuple(_job(item, base) for item in jobs_raw)
    names = [job.name for job in jobs]
    duplicates = {name for name in names if names.count(name) > 1}
    if duplicates:
        raise ConfigError(f"Имена заданий повторяются: {', '.join(sorted(duplicates))}")

    folder = base / str(storage.get("folder", "копии"))
    journal = storage.get("journal")
    return Settings(
        folder=folder,
        journal=(base / str(journal)) if journal else folder / "журнал.sqlite",
        jobs=jobs,
        drill_every_days=_positive(storage.get("drill_every_days"), "storage", "drill_every_days", DEFAULT_DRILL_DAYS),
    )


def load(path: Path) -> Settings:
    try:
        data = tomllib.loads(Path(path).read_text("utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Не удалось прочитать {Path(path).name}: {exc}") from exc
    return parse(data, Path(path).parent)


def _job(raw: object, base: Path) -> Job:
    if not isinstance(raw, dict) or not raw.get("name"):
        raise ConfigError("У каждого задания нужно имя: [[job]] name = «документы»")
    name = str(raw["name"])
    sources_raw = raw.get("sources")
    if isinstance(sources_raw, str):
        sources_raw = [sources_raw]
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError(f"Задание «{name}»: «sources» — список путей, и он не должен быть пустым")
    sources = tuple((base / str(item)).resolve() for item in sources_raw)
    # Внутри архива пути начинаются с имени источника, поэтому два источника с одинаковым именем
    # («проект/данные» и «архив/данные») молча перекрыли бы друг друга.
    names = [source.name for source in sources]
    same = {item for item in names if names.count(item) > 1}
    if same:
        raise ConfigError(f"Задание «{name}»: имена источников совпадают: {', '.join(sorted(same))}")

    excludes_raw = raw.get("excludes", [])
    if not isinstance(excludes_raw, list) or not all(isinstance(item, str) for item in excludes_raw):
        raise ConfigError(f"Задание «{name}»: «excludes» — список образцов строками, например «*.tmp»")

    return Job(
        name=name,
        sources=sources,
        excludes=tuple(str(item) for item in excludes_raw),
        compress=bool(raw.get("compress", True)),
        keep_daily=_whole(raw.get("keep_daily"), name, "keep_daily", DEFAULT_KEEP_DAILY),
        keep_weekly=_whole(raw.get("keep_weekly"), name, "keep_weekly", DEFAULT_KEEP_WEEKLY),
        keep_monthly=_whole(raw.get("keep_monthly"), name, "keep_monthly", DEFAULT_KEEP_MONTHLY),
    )


def _whole(raw: object, where: str, field: str, default: int) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ConfigError(f"«{where}»: «{field}» — целое число не меньше нуля")
    return raw


def _positive(raw: object, where: str, field: str, default: float) -> float:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int | float) or raw <= 0:
        raise ConfigError(f"«{where}»: «{field}» — положительное число")
    return float(raw)
