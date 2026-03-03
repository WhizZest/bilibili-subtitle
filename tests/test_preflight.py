from __future__ import annotations

from pathlib import Path

from bilibili_subtitle.preflight import CheckStatus, check_bbdown_auth


def _patch_home(monkeypatch, home: Path) -> None:
    monkeypatch.setattr("bilibili_subtitle.preflight.Path.home", staticmethod(lambda: home))


def test_check_bbdown_auth_detects_local_bin_cookie(monkeypatch, tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    cookie_file = local_bin / "BBDown.data"
    cookie_file.write_text("SESSDATA=abc", encoding="utf-8")

    _patch_home(monkeypatch, home)
    monkeypatch.setattr("bilibili_subtitle.preflight.shutil.which", lambda _: str(local_bin / "BBDown"))

    result = check_bbdown_auth()
    assert result.status == CheckStatus.OK
    assert result.details["cookie_file"] == str(cookie_file)


def test_check_bbdown_auth_cookie_without_sessdata(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    cookie_file = home / "BBDown.data"
    cookie_file.write_text("DedeUserID=123", encoding="utf-8")

    _patch_home(monkeypatch, home)
    monkeypatch.setattr("bilibili_subtitle.preflight.shutil.which", lambda _: None)

    result = check_bbdown_auth()
    assert result.status == CheckStatus.ERROR
    assert "no SESSDATA" in result.message
    assert str(cookie_file) in result.details["cookie_files"]


def test_check_bbdown_auth_not_logged_in(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True)

    _patch_home(monkeypatch, home)
    monkeypatch.setattr("bilibili_subtitle.preflight.shutil.which", lambda _: None)

    result = check_bbdown_auth()
    assert result.status == CheckStatus.ERROR
    assert result.message == "Not logged in"
