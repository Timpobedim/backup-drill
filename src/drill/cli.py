"""Командная строка: backup, verify, rehearse, restore, prune, list, status, demo."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from drill import demo as demo_module
from drill import report
from drill.archive import ArchiveError
from drill.config import ConfigError, Job, Settings, load
from drill.journal import Journal, JournalError
from drill.manifest import ManifestError
from drill.runner import Runner, RunnerError

CONFIG = "drill.toml"


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_console()
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ConfigError, JournalError, RunnerError, ArchiveError, ManifestError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


def _utf8_console() -> None:
    """В стандартной консоли Windows нет ни «≈», ни кавычек-ёлочек: переключаем вывод на UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() not in {"utf-8", "utf8"}:
            stream.reconfigure(encoding="utf-8", errors="replace")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drill", description="Резервные копии с проверкой восстановлением")
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="сделать копию")
    _common(backup)
    backup.set_defaults(handler=_backup)

    verify = commands.add_parser("verify", help="быстрая проверка: архивы на месте и суммы сходятся")
    _common(verify)
    verify.set_defaults(handler=_verify)

    rehearse = commands.add_parser("rehearse", help="учебная тревога: развернуть копию и сверить файлы")
    _common(rehearse)
    rehearse.add_argument("--copy", type=int, help="номер копии; по умолчанию — последняя")
    rehearse.set_defaults(handler=_rehearse)

    restore = commands.add_parser("restore", help="восстановить копию в папку")
    _common(restore)
    restore.add_argument("--copy", type=int, required=True)
    restore.add_argument("--to", type=Path, required=True)
    restore.set_defaults(handler=_restore)

    prune = commands.add_parser("prune", help="ротация по поколениям")
    _common(prune)
    prune.set_defaults(handler=_prune)

    listing = commands.add_parser("list", help="список копий")
    _common(listing)
    listing.add_argument("--limit", type=int, default=20)
    listing.set_defaults(handler=_list)

    status = commands.add_parser("status", help="состояние заданий и давность тревог")
    _common(status)
    status.set_defaults(handler=_status)

    show = commands.add_parser("demo", help="показать весь путь: копии, тревога, порча архива, ротация")
    show.add_argument("--root", type=Path)
    show.set_defaults(handler=_demo)
    return parser


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=Path(CONFIG))
    parser.add_argument("--job", help="имя задания; по умолчанию — все")


def _jobs(settings: Settings, name: str | None) -> list[Job]:
    if not name:
        return list(settings.jobs)
    job = settings.job(name)
    if job is None:
        known = ", ".join(item.name for item in settings.jobs)
        raise ConfigError(f"Задания «{name}» нет. Есть: {known}")
    return [job]


def _backup(args: argparse.Namespace) -> int:
    settings = load(args.config)
    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)
        for job in _jobs(settings, args.job):
            print(runner.backup(job).line)
    return 0


def _verify(args: argparse.Namespace) -> int:
    settings = load(args.config)
    bad = 0
    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)
        for job in _jobs(settings, args.job):
            for copy in journal.copies(job.name):
                ok = runner.verify(copy)
                bad += 0 if ok else 1
                state = "сумма сходится" if ok else "не сходится"
                print(f"{'+' if ok else '!'} копия №{copy.copy_id} «{copy.job}»: {state}")
    if bad:
        print(f"Не сошлось копий: {bad}.")
    return 1 if bad else 0


def _rehearse(args: argparse.Namespace) -> int:
    settings = load(args.config)
    failed = 0
    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)
        for job in _jobs(settings, args.job):
            copy = journal.copy(args.copy) if args.copy else journal.last_copy(job.name)
            if copy is None:
                print(f"«{job.name}»: копий ещё нет.")
                continue
            result = runner.drill(copy)
            print(result.line)
            failed += 0 if result.ok else 1
    return 1 if failed else 0


def _restore(args: argparse.Namespace) -> int:
    settings = load(args.config)
    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)
        copy = journal.copy(args.copy)
        files = runner.restore(copy, Path(args.to))
    print(f"Копия №{copy.copy_id} развёрнута в {args.to}: файлов {files}.")
    return 0


def _prune(args: argparse.Namespace) -> int:
    settings = load(args.config)
    with Journal(settings.journal) as journal:
        runner = Runner(settings, journal)
        for job in _jobs(settings, args.job):
            result = runner.prune(job)
            print(f"«{job.name}»: {result.line}")
    return 0


def _list(args: argparse.Namespace) -> int:
    settings = load(args.config)
    with Journal(settings.journal) as journal:
        copies = journal.copies(args.job, limit=args.limit)
        if not copies:
            print("Копий пока нет: запустите «drill backup».")
            return 0
        print(report.copies_table(copies))
        drills = journal.drills(args.job, limit=args.limit)
        if drills:
            print()
            print("Учебные тревоги:")
            print(report.drills_table(drills))
    return 0


def _status(args: argparse.Namespace) -> int:
    settings = load(args.config)
    with Journal(settings.journal) as journal:
        print(report.status(settings, journal))
    return 0


def _demo(args: argparse.Namespace) -> int:
    result = demo_module.run(root=args.root)
    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
