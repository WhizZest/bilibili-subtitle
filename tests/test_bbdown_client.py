"""Tests for bbdown_client.py — Fix 1 (retry/timeout), Fix 5 (regex), Fix 7 (error propagation)."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from bilibili_subtitle.bbdown_client import (
    BBDownClient,
    BBDownError,
    _SUBTITLE_LINE_RE,
    _AI_MARKER_RE,
    _LANG_RE,
    _LANG_NORMALIZE,
)


# ── Fix 5: Regex tests ──

class TestSubtitleLineRegex:
    @pytest.mark.parametrize("line", [
        "下载字幕 zh-Hans", "Download subtitle for BV123",
        "Saving subtitle file...", "字幕下载完成",
    ])
    def test_matches(self, line: str):
        assert _SUBTITLE_LINE_RE.search(line)

    def test_no_match(self):
        assert _SUBTITLE_LINE_RE.search("downloading video") is None


class TestAIMarkerRegex:
    @pytest.mark.parametrize("line", [
        "ai-zh subtitle", "AI识别字幕", "auto-generated captions",
        "asr transcription", "自动识别", "ai_en",
    ])
    def test_matches(self, line: str):
        assert _AI_MARKER_RE.search(line)

    def test_no_match(self):
        assert _AI_MARKER_RE.search("human translated") is None


class TestLangRegex:
    @pytest.mark.parametrize("text,expected", [
        ("zh-Hans", "zh"), ("zh-Hant", "zh-hant"),
        ("en", "en"), ("ja", "ja"), ("ko", "ko"),
    ])
    def test_normalize(self, text: str, expected: str):
        m = _LANG_RE.search(text)
        assert m
        raw = m.group(1).lower()
        assert _LANG_NORMALIZE.get(raw, raw) == expected


# ── Fix 1: Retry + timeout ──

def _make_client() -> BBDownClient:
    with patch.object(BBDownClient, "_find_bbdown", return_value="/usr/bin/BBDown"):
        return BBDownClient()


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.subprocess.run")
def test_succeeds_first_try(mock_run, mock_sleep):
    mock_run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
    assert _make_client()._run(["x"]).returncode == 0
    mock_sleep.assert_not_called()


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.subprocess.run")
def test_retries_transient(mock_run, mock_sleep):
    mock_run.side_effect = [
        subprocess.CompletedProcess([], 1, "", "network error"),
        subprocess.CompletedProcess([], 0, "ok", ""),
    ]
    assert _make_client()._run(["x"], retry_delay=0.01).returncode == 0
    assert mock_run.call_count == 2


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.subprocess.run")
def test_no_retry_fatal(mock_run, mock_sleep):
    mock_run.return_value = subprocess.CompletedProcess([], 1, "", "login required auth")
    with pytest.raises(BBDownError, match="non-retryable"):
        _make_client()._run(["x"])
    assert mock_run.call_count == 1


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.subprocess.run")
def test_retries_timeout(mock_run, mock_sleep):
    mock_run.side_effect = [
        subprocess.TimeoutExpired("x", 120),
        subprocess.CompletedProcess([], 0, "ok", ""),
    ]
    assert _make_client()._run(["x"], retry_delay=0.01).returncode == 0


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.subprocess.run")
def test_exhausts_retries(mock_run, mock_sleep):
    mock_run.return_value = subprocess.CompletedProcess([], 1, "", "transient")
    with pytest.raises(BBDownError):
        _make_client()._run(["x"], max_retries=2, retry_delay=0.01)
    assert mock_run.call_count == 2


# ── Fix 5: _extract_subtitle_info ──

@patch("bilibili_subtitle.bbdown_client.time.sleep")
def test_extract_subtitle_info_ai_zh(mock_sleep):
    client = _make_client()
    info = client._extract_subtitle_info("下载字幕 ai-zh\n其他行")
    assert info.has_subtitle is True
    assert info.has_ai_subtitle is True
    assert "zh" in info.languages


@patch("bilibili_subtitle.bbdown_client.time.sleep")
def test_extract_subtitle_info_no_subtitle(mock_sleep):
    client = _make_client()
    info = client._extract_subtitle_info("视频标题: test\n完成")
    assert info.has_subtitle is False
    assert info.languages == []


def test_prioritize_subtitle_files_prefers_chinese(tmp_path):
    client = _make_client()
    paths = [
        tmp_path / "BV1xxx.ai-en.srt",
        tmp_path / "BV1xxx.ai-zh.srt",
        tmp_path / "BV1xxx.es.srt",
        tmp_path / "BV1xxx.zh.srt",
    ]
    for p in paths:
        p.write_text("", encoding="utf-8")

    ordered = client._prioritize_subtitle_files(paths)
    assert ordered[0].name.endswith(".ai-zh.srt")
    assert ordered[1].name.endswith(".zh.srt")


@patch("bilibili_subtitle.bbdown_client.time.sleep")
@patch("bilibili_subtitle.bbdown_client.BBDownClient._extract_video_id", return_value="BV1test12345")
@patch("bilibili_subtitle.bbdown_client.BBDownClient._run")
def test_get_video_info_retries_without_select_lang(mock_run, _mock_extract_video_id, _mock_sleep, tmp_path):
    client = _make_client()

    def run_side_effect(args, **kwargs):
        if "--select-lang" in args:
            return subprocess.CompletedProcess(
                args=args,
                returncode=1,
                stdout="",
                stderr="Unrecognized command or argument 'zh-Hans'.",
            )
        subtitle_file = tmp_path / "BV1test12345.ai-zh.srt"
        subtitle_file.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="下载字幕 ai-zh",
            stderr="",
        )

    mock_run.side_effect = run_side_effect
    info = client.get_video_info("https://www.bilibili.com/video/BV1test12345", tmp_path, lang="zh-Hans")

    assert mock_run.call_count == 2
    assert info.subtitle_files
    assert info.subtitle_files[0].name.endswith(".ai-zh.srt")
