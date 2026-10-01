"""Отчёты: копии, учения и главный вопрос — когда копии в последний раз разворачивали."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from drill.config import Settings
from drill.journal import Copy, DrillRun, Journal

UNITS = (("ТБ", 1024**4), ("ГБ", 1024**3), ("МБ", 1024**2), ("КБ", 1024), ("Б", 1))


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], align: str = "") -> str:
    columns = len(headers)
    widths = [len(header) for header in headers]
    for row in rows:
        for index in range(columns):
            widths[index] = max(widths[index], len(row[index]))
    rules = (align + "l" * columns)[:columns]

    def render(cells: Sequence[str]) -> str:
        parts = [
            cells[index].rjust(widths[index]) if rules[index] == "r" else cells[index].ljust(widths[index])
            for index in range(columns)
        ]
        return "  ".join(parts).rstrip()

    return "\n".join([render(headers), *(render(row) for row in rows)])


def size(value: int) -> str:
    for name, step in UNITS:
        if value >= step or name == "Б":
            number = value / step
            return f"{number:.1f} {name}" if step > 1 else f"{value} {name}"
    return f"{value} Б"


def ago(moment: datetime, now: datetime) -> str:
    delta = now - moment
    if delta < timedelta(minutes=1):
        return "только что"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} мин назад"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} ч назад"
    return f"{delta.days} дн. назад"


def copies_table(copies: Sequence[Copy], *, now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    rows = [
        [
            str(copy.copy_id),
            copy.job,
            f"{copy.created_at.astimezone(UTC):%d.%m %H:%M}",
            ago(copy.created_at, moment),
            str(copy.files),
            size(copy.size),
            "на месте" if copy.path.exists() else "файла нет",
        ]
        for copy in copies
    ]
    return table(["№", "Задание", "Когда", "Возраст", "Файлов", "Архив", "Состояние"], rows, align="lll" + "lrrl")


def drills_table(drills: Sequence[DrillRun], *, now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    rows = [
        [
            str(run.drill_id),
            str(run.copy_id),
            run.job,
            ago(run.started_at, moment),
            "прошла" if run.ok else "провалена",
            str(run.checked),
            run.detail[:48],
        ]
        for run in drills
    ]
    return table(["№", "Копия", "Задание", "Когда", "Итог", "Файлов", "Подробности"], rows, align="lll" + "llrl")


def status(settings: Settings, journal: Journal, *, now: datetime | None = None) -> str:
    """Главная страница: по каждому заданию — последняя копия и последняя успешная тревога."""
    moment = now or datetime.now(UTC)
    rows: list[list[str]] = []
    warnings: list[str] = []
    for job in settings.jobs:
        copy = journal.last_copy(job.name)
        good = journal.last_good_drill(job.name)
        total = len(journal.copies(job.name, limit=10_000))
        rows.append(
            [
                job.name,
                str(total),
                ago(copy.created_at, moment) if copy else "копий нет",
                size(copy.size) if copy else "—",
                ago(good.started_at, moment) if good else "ни разу",
            ]
        )
        if copy is None:
            warnings.append(f"«{job.name}»: копий ещё нет")
            continue
        if good is None:
            warnings.append(f"«{job.name}»: восстановление ни разу не проверялось — это ещё не резервная копия")
        elif moment - good.started_at > timedelta(days=settings.drill_every_days):
            days = (moment - good.started_at).days
            warnings.append(f"«{job.name}»: последняя успешная тревога была {days} дн. назад")
    parts = [table(["Задание", "Копий", "Последняя", "Размер", "Тревога"], rows, align="lrllr")]
    if warnings:
        parts += ["", *(f"! {line}" for line in warnings)]
    else:
        parts += ["", "Все задания в порядке: копии свежие, тревоги проходят."]
    return "\n".join(parts)
