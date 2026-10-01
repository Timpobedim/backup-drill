from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from drill.config import Job, Settings
from drill.journal import Journal
from drill.runner import Runner

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def make_data(root: Path) -> Path:
    """Небольшой набор файлов: вложенная папка, обычные файлы и временный, который исключён."""
    documents = root / "документы"
    (documents / "вложенная").mkdir(parents=True, exist_ok=True)
    (documents / "договор.txt").write_text("Договор\n", "utf-8")
    (documents / "смета.csv").write_text("статья;сумма\nработы;120000\n", "utf-8")
    (documents / "черновик.tmp").write_text("временный\n", "utf-8")
    (documents / "вложенная" / "акт.txt").write_text("Акт\n", "utf-8")
    return documents


def make_job(source: Path, **changes: object) -> Job:
    values: dict[str, object] = {
        "name": "документы",
        "sources": (source,),
        "excludes": ("*.tmp",),
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 6,
    }
    values.update(changes)
    return Job(**values)  # type: ignore[arg-type]


def make_settings(root: Path, job: Job) -> Settings:
    return Settings(folder=root / "копии", journal=root / "копии" / "журнал.sqlite", jobs=(job,))


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return make_data(tmp_path / "данные")


@pytest.fixture
def job(data: Path) -> Job:
    return make_job(data)


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Journal]:
    book = Journal(tmp_path / "копии" / "журнал.sqlite")
    yield book
    book.close()


@pytest.fixture
def runner(tmp_path: Path, job: Job, journal: Journal) -> Runner:
    return Runner(make_settings(tmp_path, job), journal)
