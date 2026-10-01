from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

import pytest
from conftest import NOW

from drill.journal import Journal, JournalError


def add(journal: Journal, *, job: str = "документы", days: int = 0, copy_id_path: str = "копия.tar.gz") -> int:
    copy = journal.add_copy(
        job=job,
        created_at=NOW - timedelta(days=days),
        path=Path(copy_id_path),
        manifest_path=Path("опись.json"),
        size=1024,
        digest="a" * 64,
        files=3,
        bytes_total=2048,
    )
    return copy.copy_id


def test_copy_is_written_and_read_back(journal: Journal) -> None:
    number = add(journal)
    copy = journal.copy(number)
    assert copy.job == "документы"
    assert copy.files == 3
    assert copy.size == 1024
    assert copy.created_at == NOW
    assert copy.created_at.tzinfo == UTC


def test_copies_come_newest_first(journal: Journal) -> None:
    add(journal, days=2)
    add(journal, days=0)
    add(journal, days=1)
    copies = journal.copies("документы")
    assert [copy.created_at for copy in copies] == [NOW, NOW - timedelta(days=1), NOW - timedelta(days=2)]
    assert journal.last_copy("документы") is not None
    assert journal.last_copy("документы").created_at == NOW  # type: ignore[union-attr]
    assert journal.last_copy("нет такого") is None


def test_limit_and_filter_by_job(journal: Journal) -> None:
    add(journal, job="документы")
    add(journal, job="база", days=1)
    assert len(journal.copies(limit=10)) == 2
    assert [copy.job for copy in journal.copies("база")] == ["база"]
    assert len(journal.copies(limit=1)) == 1


def test_forgotten_copy_disappears(journal: Journal) -> None:
    number = add(journal)
    journal.forget(number)
    assert journal.copies("документы") == []
    with pytest.raises(JournalError, match="нет в журнале"):
        journal.copy(number)


def test_drills_are_recorded(journal: Journal) -> None:
    number = add(journal)
    journal.add_drill(
        copy_id=number,
        job="документы",
        started_at=NOW - timedelta(days=1),
        ok=False,
        checked=0,
        detail="сумма",
        seconds=0.2,
    )
    journal.add_drill(
        copy_id=number, job="документы", started_at=NOW, ok=True, checked=3, detail="проверено", seconds=0.4
    )
    runs = journal.drills("документы")
    assert [run.ok for run in runs] == [True, False]
    good = journal.last_good_drill("документы")
    assert good is not None
    assert good.checked == 3
    assert journal.last_good_drill("база") is None


def test_restores_are_recorded(journal: Journal, tmp_path: Path) -> None:
    number = add(journal)
    journal.add_restore(copy_id=number, at=NOW, target=tmp_path / "куда", files=3)
    count = journal.connection.execute("SELECT count(*) FROM restores").fetchone()[0]
    assert count == 1


def test_journal_creates_its_folder(tmp_path: Path) -> None:
    path = tmp_path / "новая" / "папка" / "журнал.sqlite"
    with Journal(path) as book:
        assert book.copies() == []
    assert path.exists()
