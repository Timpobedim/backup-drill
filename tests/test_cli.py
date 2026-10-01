from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_data

from drill.cli import main


@pytest.fixture
def stand(tmp_path: Path) -> Path:
    """Готовый стенд: данные, файл настроек и одна сделанная копия."""
    make_data(tmp_path / "данные")
    config = tmp_path / "drill.toml"
    config.write_text(
        "[storage]\n"
        'folder = "копии"\n'
        "drill_every_days = 7\n\n"
        "[[job]]\n"
        'name = "документы"\n'
        'sources = ["данные/документы"]\n'
        'excludes = ["*.tmp"]\n'
        "keep_daily = 2\n"
        "keep_weekly = 0\n"
        "keep_monthly = 0\n",
        encoding="utf-8",
    )
    assert main(["backup", "--config", str(config)]) == 0
    return config


def test_backup_reports_the_copy(stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    capsys.readouterr()
    assert main(["backup", "--config", str(stand)]) == 0
    printed = capsys.readouterr().out
    assert "файлов 3" in printed


def test_list_shows_copies(stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list", "--config", str(stand)]) == 0
    printed = capsys.readouterr().out
    assert "документы" in printed
    assert "на месте" in printed


def test_rehearse_and_verify_pass(stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["rehearse", "--config", str(stand)]) == 0
    assert "Тревога по копии" in capsys.readouterr().out
    assert main(["verify", "--config", str(stand)]) == 0
    assert "сумма сходится" in capsys.readouterr().out


def test_damaged_archive_fails_both_checks(stand: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    archive = next((tmp_path / "копии" / "документы").glob("*.tar.gz"))
    with archive.open("ab") as handle:
        handle.write(b"\x00" + "мусор".encode())

    assert main(["verify", "--config", str(stand)]) == 1
    assert "не сходится" in capsys.readouterr().out
    assert main(["rehearse", "--config", str(stand)]) == 1
    assert "сумма архива не совпадает" in capsys.readouterr().out


def test_restore_unpacks_the_copy(stand: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    where = tmp_path / "восстановлено"
    assert main(["restore", "--config", str(stand), "--copy", "1", "--to", str(where)]) == 0
    assert (where / "документы" / "смета.csv").exists()
    assert "развёрнута" in capsys.readouterr().out


def test_status_warns_until_the_first_drill(stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["status", "--config", str(stand)]) == 0
    printed = capsys.readouterr().out
    assert "ни разу" in printed
    assert "это ещё не резервная копия" in printed

    main(["rehearse", "--config", str(stand)])
    capsys.readouterr()
    assert main(["status", "--config", str(stand)]) == 0
    assert "в порядке" in capsys.readouterr().out


def test_prune_removes_extra_copies(stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["backup", "--config", str(stand)])
    capsys.readouterr()
    assert main(["prune", "--config", str(stand)]) == 0
    assert "оставлено" in capsys.readouterr().out


def test_unknown_job_and_missing_config(tmp_path: Path, stand: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["backup", "--config", str(stand), "--job", "нет-такого"]) == 2
    assert "Есть: документы" in capsys.readouterr().err
    assert main(["status", "--config", str(tmp_path / "нет.toml")]) == 2
    assert "Не удалось прочитать" in capsys.readouterr().err


def test_demo_tells_the_story(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--root", str(tmp_path / "демо")]) == 0
    printed = capsys.readouterr().out
    assert "Тревога по копии" in printed
    assert "сумма архива не совпадает" in printed, "испорченный архив должен быть пойман"
    assert "Ротация:" in printed
