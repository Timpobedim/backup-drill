"""Операции: копия, проверка суммы, учебная тревога, восстановление и ротация.

Учебная тревога — главное здесь. Копия, которую ни разу не разворачивали, — это не резервная копия,
а надежда: архив может быть обрезан, опись — не совпадать, а пароль от шифрования — потеряться.
Тревога разворачивает копию во временную папку и сверяет каждый файл по контрольной сумме, после
чего временная папка удаляется.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from drill import archive, manifest
from drill.config import Job, Settings
from drill.journal import Copy, Journal
from drill.manifest import Difference, Manifest


class RunnerError(RuntimeError):
    """Операцию выполнить не удалось; текст объясняет, что именно случилось."""


@dataclass(frozen=True, slots=True)
class BackupResult:
    copy: Copy
    seconds: float

    @property
    def line(self) -> str:
        return (
            f"Копия №{self.copy.copy_id} «{self.copy.job}»: файлов {self.copy.files}, "
            f"архив {self.copy.size} байт, за {self.seconds:.2f} с"
        )


@dataclass(frozen=True, slots=True)
class DrillResult:
    copy: Copy
    ok: bool
    checked: int
    difference: Difference
    detail: str
    seconds: float

    @property
    def line(self) -> str:
        mark = "+" if self.ok else "!"
        return f"{mark} Тревога по копии №{self.copy.copy_id} «{self.copy.job}»: {self.detail} ({self.seconds:.2f} с)"


@dataclass(frozen=True, slots=True)
class PruneResult:
    removed: tuple[Copy, ...]
    kept: tuple[Copy, ...]

    @property
    def line(self) -> str:
        return f"Ротация: оставлено {len(self.kept)}, удалено {len(self.removed)}."


class Runner:
    """Всё, что можно сделать с копиями одного хранилища."""

    def __init__(self, settings: Settings, journal: Journal) -> None:
        self.settings = settings
        self.journal = journal

    # ── копия ───────────────────────────────────────────────────────────────────────────────────

    def backup(self, job: Job, *, now: datetime | None = None) -> BackupResult:
        started = time.monotonic()
        moment = now or datetime.now(UTC)
        try:
            description = manifest.collect(job.name, job.sources, excludes=job.excludes, now=moment)
        except manifest.ManifestError as exc:
            raise RunnerError(str(exc)) from exc

        folder = self.settings.folder / job.name
        stamp = moment.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
        target = folder / f"{job.name}-{stamp}{job.suffix}"
        manifest_path = folder / f"{job.name}-{stamp}.опись.json"

        info = archive.create(
            description, roots={source.name: source for source in job.sources}, target=target, compress=job.compress
        )
        manifest_path.write_text(description.to_json(), "utf-8")

        copy = self.journal.add_copy(
            job=job.name,
            created_at=moment,
            path=info.path,
            manifest_path=manifest_path,
            size=info.size,
            digest=info.digest,
            files=description.files,
            bytes_total=description.total_size,
        )
        return BackupResult(copy=copy, seconds=time.monotonic() - started)

    # ── проверки ────────────────────────────────────────────────────────────────────────────────

    def verify(self, copy: Copy) -> bool:
        """Быстрая проверка: файл на месте и его сумма совпадает с записанной в журнале."""
        return archive.same(copy.path, copy.digest)

    def drill(self, copy: Copy, *, now: datetime | None = None) -> DrillResult:
        """Учебная тревога: развернуть копию во временную папку и сверить каждый файл."""
        started = time.monotonic()
        moment = now or datetime.now(UTC)

        if not copy.path.exists():
            return self._record_drill(copy, moment, False, 0, "архива нет на месте", started)
        if not archive.same(copy.path, copy.digest):
            return self._record_drill(copy, moment, False, 0, "сумма архива не совпадает с журналом", started)
        try:
            stored = Manifest.from_json(copy.manifest_path.read_text("utf-8"))
        except (OSError, manifest.ManifestError) as exc:
            return self._record_drill(copy, moment, False, 0, f"опись не прочитать: {exc}", started)

        temporary = Path(tempfile.mkdtemp(prefix="drill-"))
        try:
            archive.extract(copy.path, temporary)
            restored = manifest.scan(temporary, job_name=copy.job, now=moment)
            difference = stored.compare(restored)
            detail = difference.line() if not difference.ok else f"проверено файлов: {restored.files}"
            return self._record_drill(copy, moment, difference.ok, restored.files, detail, started, difference)
        except archive.ArchiveError as exc:
            return self._record_drill(copy, moment, False, 0, f"распаковка не удалась: {exc}", started)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def restore(self, copy: Copy, to: Path, *, now: datetime | None = None) -> int:
        """Настоящее восстановление — то же самое, но в указанную папку и с записью в журнал."""
        if not archive.same(copy.path, copy.digest):
            raise RunnerError(f"Копия №{copy.copy_id}: сумма архива не совпадает с журналом, восстанавливать нельзя")
        files = archive.extract(copy.path, to)
        self.journal.add_restore(copy_id=copy.copy_id, at=now or datetime.now(UTC), target=to, files=files)
        return files

    # ── ротация ─────────────────────────────────────────────────────────────────────────────────

    def prune(self, job: Job) -> PruneResult:
        """Оставляет по одной копии за день, неделю и месяц — сколько указано в настройках."""
        copies = self.journal.copies(job.name, limit=10_000)
        keep: dict[int, Copy] = {}
        for period, limit in (("day", job.keep_daily), ("week", job.keep_weekly), ("month", job.keep_monthly)):
            seen: set[str] = set()
            for copy in copies:  # журнал отдаёт от новых к старым
                key = _period_key(copy.created_at, period)
                if key in seen:
                    continue
                if len(seen) >= limit:
                    break
                seen.add(key)
                keep[copy.copy_id] = copy

        removed: list[Copy] = []
        for copy in copies:
            if copy.copy_id in keep:
                continue
            copy.path.unlink(missing_ok=True)
            copy.manifest_path.unlink(missing_ok=True)
            self.journal.forget(copy.copy_id)
            removed.append(copy)
        return PruneResult(removed=tuple(removed), kept=tuple(keep.values()))

    def _record_drill(
        self,
        copy: Copy,
        moment: datetime,
        ok: bool,
        checked: int,
        detail: str,
        started: float,
        difference: Difference | None = None,
    ) -> DrillResult:
        seconds = time.monotonic() - started
        self.journal.add_drill(
            copy_id=copy.copy_id,
            job=copy.job,
            started_at=moment,
            ok=ok,
            checked=checked,
            detail=detail,
            seconds=seconds,
        )
        return DrillResult(
            copy=copy,
            ok=ok,
            checked=checked,
            difference=difference or Difference(),
            detail=detail,
            seconds=seconds,
        )


def _period_key(moment: datetime, period: str) -> str:
    local = moment.astimezone(UTC)
    if period == "day":
        return local.strftime("%Y-%m-%d")
    if period == "week":
        year, week, _ = local.isocalendar()
        return f"{year}-н{week:02d}"
    return local.strftime("%Y-%m")
