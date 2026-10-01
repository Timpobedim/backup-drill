"""Демонстрация: три копии, учебная тревога, испорченный архив и ротация.

Сценарий подобран так, чтобы было видно главное: копия, которую никто не разворачивал, ничего не
доказывает. Один архив здесь портится намеренно — и тревога находит это раньше, чем понадобится
восстановление.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drill import report
from drill.config import Job, Settings
from drill.journal import Journal
from drill.runner import Runner


@dataclass(frozen=True, slots=True)
class DemoResult:
    root: Path
    text: str
    good_drill: bool
    bad_drill: bool


def run(*, root: Path | None = None, now: datetime | None = None) -> DemoResult:
    base = Path(root) if root else Path(tempfile.mkdtemp(prefix="backup-drill-demo-"))
    moment = now or datetime.now(UTC)
    data = base / "данные"
    _make_data(data)

    job = Job(
        name="документы",
        sources=(data / "документы",),
        excludes=("*.tmp",),
        keep_daily=2,
        keep_weekly=0,
        keep_monthly=0,
    )
    settings = Settings(folder=base / "копии", journal=base / "копии" / "журнал.sqlite", jobs=(job,))

    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)

        first = runner.backup(job, now=moment - timedelta(days=2))
        (data / "документы" / "договор.txt").write_text("Договор, редакция 2\n", "utf-8")
        second = runner.backup(job, now=moment - timedelta(days=1))
        (data / "документы" / "новый.txt").write_text("Появился после второй копии\n", "utf-8")
        third = runner.backup(job, now=moment)

        good = runner.drill(third.copy, now=moment)

        # Портим архив вчерашней копии: дописываем мусор в конец файла.
        with second.copy.path.open("ab") as handle:
            handle.write(b"\x00" + "мусор".encode())
        bad = runner.drill(second.copy, now=moment)

        sums = [(copy.copy_id, runner.verify(copy)) for copy in journal.copies(job.name)]
        pruned = runner.prune(job)

        text = "\n".join(
            [
                f"Данные: {third.copy.files} файлов, {report.size(third.copy.bytes_total)}.",
                "",
                "Копии:",
                report.copies_table(journal.copies(job.name), now=moment),
                "",
                good.line,
                bad.line,
                "",
                "Быстрая проверка сумм: "
                + ", ".join(f"№{number} — {'в порядке' if ok else 'не совпала'}" for number, ok in sums),
                "",
                pruned.line,
                f"Удалена копия №{pruned.removed[0].copy_id} от {pruned.removed[0].created_at:%d.%m}"
                if pruned.removed
                else "Ротация ничего не удалила",
                "",
                "Состояние заданий:",
                report.status(settings, journal, now=moment),
                "",
                f"Первая копия была №{first.copy.copy_id}. Файлы демонстрации: {base}",
            ]
        )
    return DemoResult(root=base, text=text, good_drill=good.ok, bad_drill=bad.ok)


def _make_data(data: Path) -> None:
    documents = data / "документы"
    (documents / "вложенная").mkdir(parents=True, exist_ok=True)
    (documents / "договор.txt").write_text("Договор, редакция 1\n", "utf-8")
    (documents / "смета.csv").write_text("статья;сумма\nработы;120000\n", "utf-8")
    (documents / "черновик.tmp").write_text("временный файл, в копию не попадёт\n", "utf-8")
    (documents / "вложенная" / "акт.txt").write_text("Акт выполненных работ\n", "utf-8")
