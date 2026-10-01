from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from conftest import NOW, make_job, make_settings

from drill.config import Job
from drill.journal import Journal
from drill.runner import Runner, RunnerError


def test_backup_creates_archive_manifest_and_record(runner: Runner, job: Job) -> None:
    result = runner.backup(job, now=NOW)
    copy = result.copy

    assert copy.path.exists()
    assert copy.manifest_path.exists()
    assert copy.files == 3, "черновик.tmp исключён"
    assert copy.size > 0
    assert "документы-20260310" in copy.path.name
    assert runner.journal.last_copy("документы") is not None


def test_backup_of_a_missing_source_is_explained(tmp_path: Path, journal: Journal) -> None:
    job = make_job(tmp_path / "нет-такой-папки")
    runner = Runner(make_settings(tmp_path, job), journal)
    with pytest.raises(RunnerError, match="Источник не найден"):
        runner.backup(job, now=NOW)


def test_drill_passes_on_a_fresh_copy(runner: Runner, job: Job) -> None:
    copy = runner.backup(job, now=NOW).copy
    result = runner.drill(copy, now=NOW)

    assert result.ok
    assert result.checked == 3
    assert result.difference.ok
    assert "проверено файлов: 3" in result.detail
    good = runner.journal.last_good_drill("документы")
    assert good is not None


def test_drill_notices_a_damaged_archive(runner: Runner, job: Job) -> None:
    copy = runner.backup(job, now=NOW).copy
    with copy.path.open("ab") as handle:
        handle.write(b"\x00" + "мусор".encode())

    result = runner.drill(copy, now=NOW)
    assert not result.ok
    assert "сумма архива не совпадает" in result.detail
    assert runner.journal.last_good_drill("документы") is None


def test_drill_notices_a_missing_archive(runner: Runner, job: Job) -> None:
    copy = runner.backup(job, now=NOW).copy
    copy.path.unlink()
    result = runner.drill(copy, now=NOW)
    assert not result.ok
    assert "архива нет" in result.detail


def test_drill_notices_a_broken_manifest(runner: Runner, job: Job) -> None:
    copy = runner.backup(job, now=NOW).copy
    copy.manifest_path.write_text("{это не опись}", "utf-8")
    result = runner.drill(copy, now=NOW)
    assert not result.ok
    assert "опись не прочитать" in result.detail


def test_verify_is_a_quick_check(runner: Runner, job: Job) -> None:
    copy = runner.backup(job, now=NOW).copy
    assert runner.verify(copy)
    with copy.path.open("ab") as handle:
        handle.write(b"\x00")
    assert not runner.verify(copy)


def test_restore_puts_files_back(runner: Runner, job: Job, tmp_path: Path) -> None:
    copy = runner.backup(job, now=NOW).copy
    where = tmp_path / "восстановлено"
    assert runner.restore(copy, where, now=NOW) == 3
    assert (where / "документы" / "договор.txt").read_text("utf-8") == "Договор\n"
    assert (where / "документы" / "вложенная" / "акт.txt").exists()
    assert not (where / "документы" / "черновик.tmp").exists()


def test_restore_refuses_a_damaged_copy(runner: Runner, job: Job, tmp_path: Path) -> None:
    copy = runner.backup(job, now=NOW).copy
    with copy.path.open("ab") as handle:
        handle.write(b"\x00")
    with pytest.raises(RunnerError, match="восстанавливать нельзя"):
        runner.restore(copy, tmp_path / "куда", now=NOW)


def three_copies(runner: Runner, job: Job, days: tuple[int, ...]) -> list[Path]:
    return [runner.backup(job, now=NOW - timedelta(days=day)).copy.path for day in days]


def test_prune_keeps_the_newest_days(tmp_path: Path, data: Path, journal: Journal) -> None:
    job = make_job(data, keep_daily=2, keep_weekly=0, keep_monthly=0)
    runner = Runner(make_settings(tmp_path, job), journal)
    paths = three_copies(runner, job, (2, 1, 0))

    result = runner.prune(job)
    assert len(result.kept) == 2
    assert len(result.removed) == 1
    assert result.removed[0].created_at == NOW - timedelta(days=2)
    assert not paths[0].exists(), "файл удалённой копии тоже должен исчезнуть"
    assert paths[1].exists()
    assert len(journal.copies("документы")) == 2


def test_monthly_generation_keeps_older_copies(tmp_path: Path, data: Path, journal: Journal) -> None:
    job = make_job(data, keep_daily=1, keep_weekly=1, keep_monthly=3)
    runner = Runner(make_settings(tmp_path, job), journal)
    for moment in (datetime(2026, 1, 15, 12, tzinfo=NOW.tzinfo), datetime(2026, 2, 15, 12, tzinfo=NOW.tzinfo), NOW):
        runner.backup(job, now=moment)

    result = runner.prune(job)
    assert result.removed == ()
    assert len(journal.copies("документы")) == 3

    tight = make_job(data, keep_daily=1, keep_weekly=1, keep_monthly=1)
    tight_result = Runner(make_settings(tmp_path, tight), journal).prune(tight)
    assert len(tight_result.removed) == 2
    assert [copy.created_at for copy in journal.copies("документы")] == [NOW]


def test_prune_on_empty_journal_is_quiet(runner: Runner, job: Job) -> None:
    result = runner.prune(job)
    assert result.removed == ()
    assert result.kept == ()
    assert "оставлено 0" in result.line
