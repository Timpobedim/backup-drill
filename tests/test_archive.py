from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from conftest import NOW

from drill import archive, manifest
from drill.archive import ArchiveError


def test_archive_round_trip(tmp_path: Path, data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    info = archive.create(description, roots={data.name: data}, target=tmp_path / "копия.tar.gz")

    assert info.path.exists()
    assert info.size > 0
    assert len(info.digest) == 64
    assert not list(tmp_path.glob("*.tmp")), "временный файл не должен оставаться"

    where = tmp_path / "восстановлено"
    assert archive.extract(info.path, where) == 3
    restored = manifest.scan(where, now=NOW)
    assert description.compare(restored).ok


def test_uncompressed_archive_also_works(tmp_path: Path, data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    info = archive.create(description, roots={data.name: data}, target=tmp_path / "копия.tar", compress=False)
    assert archive.extract(info.path, tmp_path / "куда") == 3


def test_digest_notices_damage(tmp_path: Path, data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    info = archive.create(description, roots={data.name: data}, target=tmp_path / "копия.tar.gz")
    assert archive.same(info.path, info.digest)

    with info.path.open("ab") as handle:
        handle.write(b"\x00" + "мусор".encode())
    assert not archive.same(info.path, info.digest)


def test_unknown_source_is_refused(tmp_path: Path, data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    with pytest.raises(ArchiveError, match="Неизвестный источник"):
        archive.create(description, roots={}, target=tmp_path / "копия.tar.gz")


def test_missing_archive_is_explained(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError, match="Не удалось распаковать"):
        archive.extract(tmp_path / "нет-такого.tar.gz", tmp_path / "куда")
    assert not archive.same(tmp_path / "нет-такого.tar.gz", "0" * 64)


def test_path_traversal_is_refused(tmp_path: Path) -> None:
    """Архив — это данные извне: запись «../беглец.txt» не должна попасть за пределы папки."""
    evil = tmp_path / "злой.tar"
    payload = "сбежал".encode()
    with tarfile.open(evil, "w") as handle:
        info = tarfile.TarInfo("../беглец.txt")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))

    with pytest.raises(ArchiveError):
        archive.extract(evil, tmp_path / "куда")
    assert not (tmp_path / "беглец.txt").exists()
