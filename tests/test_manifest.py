from __future__ import annotations

from pathlib import Path

import pytest
from conftest import NOW, make_data

from drill import manifest
from drill.manifest import Manifest, ManifestError


def test_files_are_collected_with_source_prefix(data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    assert [entry.path for entry in description.entries] == [
        "документы/вложенная/акт.txt",
        "документы/договор.txt",
        "документы/смета.csv",
    ]
    assert description.files == 3
    assert description.total_size > 0
    assert all(len(entry.digest) == 64 for entry in description.entries)


def test_excludes_work_by_name_and_by_path(data: Path) -> None:
    by_name = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    assert not any("черновик" in entry.path for entry in by_name.entries)

    by_path = manifest.collect("документы", [data], excludes=("*/вложенная/*",), now=NOW)
    assert not any("вложенная" in entry.path for entry in by_path.entries)


def test_single_file_source(tmp_path: Path) -> None:
    path = tmp_path / "дамп.sql"
    path.write_text("SELECT 1;\n", "utf-8")
    description = manifest.collect("база", [path], now=NOW)
    assert [entry.path for entry in description.entries] == ["дамп.sql"]


def test_missing_source_is_explained(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="Источник не найден"):
        manifest.collect("документы", [tmp_path / "нет-такой"], now=NOW)


def test_digest_changes_with_content(tmp_path: Path) -> None:
    path = tmp_path / "файл.txt"
    path.write_text("один\n", "utf-8")
    first = manifest.digest_of(path)
    path.write_text("два\n", "utf-8")
    assert manifest.digest_of(path) != first


def test_json_round_trip(data: Path) -> None:
    description = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    restored = Manifest.from_json(description.to_json())
    assert restored.job == description.job
    assert restored.files == description.files
    assert [entry.digest for entry in restored.entries] == [entry.digest for entry in description.entries]


def test_broken_json_is_explained() -> None:
    with pytest.raises(ManifestError, match="Опись повреждена"):
        Manifest.from_json("{это не опись}")


def test_comparison_finds_every_kind_of_difference(tmp_path: Path) -> None:
    source = make_data(tmp_path / "данные")
    stored = manifest.collect("документы", [source], excludes=("*.tmp",), now=NOW)

    (source / "договор.txt").write_text("Договор, редакция 2\n", "utf-8")
    (source / "смета.csv").unlink()
    (source / "лишний.txt").write_text("появился\n", "utf-8")
    restored = manifest.collect("документы", [source], excludes=("*.tmp",), now=NOW)

    difference = stored.compare(restored)
    assert difference.missing == ("документы/смета.csv",)
    assert difference.changed == ("документы/договор.txt",)
    assert difference.extra == ("документы/лишний.txt",)
    assert not difference.ok
    assert "не хватает 1" in difference.line()


def test_identical_manifests_match(data: Path) -> None:
    first = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    second = manifest.collect("документы", [data], excludes=("*.tmp",), now=NOW)
    assert first.compare(second).ok
    assert first.compare(second).line() == "все файлы совпали"


def test_scan_reads_an_unpacked_copy(tmp_path: Path, data: Path) -> None:
    scanned = manifest.scan(data.parent, now=NOW)
    assert any(entry.path.endswith("договор.txt") for entry in scanned.entries)
