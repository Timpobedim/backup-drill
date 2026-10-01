from __future__ import annotations

from pathlib import Path

import pytest

from drill.config import ConfigError, load, parse

GOOD = {
    "storage": {"folder": "копии", "journal": "копии/журнал.sqlite", "drill_every_days": 3},
    "job": [
        {"name": "документы", "sources": ["данные/документы"], "excludes": ["*.tmp"], "keep_daily": 5},
        {"name": "база", "sources": "данные/дампы", "compress": False, "keep_weekly": 0},
    ],
}


def test_settings_are_read(tmp_path: Path) -> None:
    settings = parse(GOOD, tmp_path)
    assert [job.name for job in settings.jobs] == ["документы", "база"]
    assert settings.folder == tmp_path / "копии"
    assert settings.drill_every_days == 3
    assert settings.jobs[0].keep_daily == 5
    assert settings.jobs[0].excludes == ("*.tmp",)
    assert settings.jobs[1].sources[0].name == "дампы", "одиночный путь строкой тоже принимается"
    assert settings.jobs[1].suffix == ".tar"
    assert settings.jobs[0].suffix == ".tar.gz"
    assert settings.job("база") is not None
    assert settings.job("нет такого") is None


def test_defaults_are_sensible(tmp_path: Path) -> None:
    settings = parse({"job": [{"name": "а", "sources": ["данные"]}]}, tmp_path)
    job = settings.jobs[0]
    assert (job.keep_daily, job.keep_weekly, job.keep_monthly) == (7, 4, 6)
    assert job.compress
    assert settings.journal == tmp_path / "копии" / "журнал.sqlite"


@pytest.mark.parametrize(
    ("broken", "message"),
    [
        ({"job": []}, "хотя бы одно задание"),
        ({"job": [{"sources": ["данные"]}]}, "нужно имя"),
        ({"job": [{"name": "а"}]}, "«sources» — список путей"),
        ({"job": [{"name": "а", "sources": []}]}, "«sources» — список путей"),
        ({"job": [{"name": "а", "sources": ["д"], "excludes": "*.tmp"}]}, "«excludes» — список образцов"),
        ({"job": [{"name": "а", "sources": ["д"], "keep_daily": -1}]}, "не меньше нуля"),
        ({"job": [{"name": "а", "sources": ["д"]}, {"name": "а", "sources": ["е"]}]}, "повторяются"),
        ({"job": [{"name": "а", "sources": ["один/данные", "два/данные"]}]}, "имена источников совпадают"),
        ({"storage": [], "job": [{"name": "а", "sources": ["д"]}]}, "таблица настроек"),
        ({"storage": {"drill_every_days": 0}, "job": [{"name": "а", "sources": ["д"]}]}, "положительное число"),
    ],
)
def test_mistakes_are_explained(broken: dict[str, object], message: str, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=message):
        parse(broken, tmp_path)


def test_file_is_read(tmp_path: Path) -> None:
    path = tmp_path / "drill.toml"
    path.write_text(
        '[storage]\nfolder = "копии"\n\n[[job]]\nname = "документы"\nsources = ["данные"]\n', encoding="utf-8"
    )
    settings = load(path)
    assert settings.jobs[0].name == "документы"
    assert settings.folder == tmp_path / "копии"

    broken = tmp_path / "плохой.toml"
    broken.write_text("[storage\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        load(broken)
    with pytest.raises(ConfigError, match="Не удалось прочитать"):
        load(tmp_path / "нет-файла.toml")
