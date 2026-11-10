"""config.toml ملف محلي — يجب ألا يكون مُتتبَّعاً في git.

السبب: البوت يحفظ إعداداتك في config.toml أثناء عمله (/set، /live، /tf…)،
فلو كان الملف مُتتبَّعاً رفض git السحب وتعطّل update.bat.

النسخة المرجعية التي تُرفع على GitHub هي config.example.toml،
وConfig.load() ينسخها تلقائياً إن لم يوجد config.toml.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig import config as config_module  # noqa: E402
from stratig.config import Config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_config_toml_is_not_tracked_by_git():
    """config.toml غير مُتتبَّع — وإلا تعطّل git pull على جهاز المستخدم."""
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config.toml"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode != 0, "config.toml مُتتبَّع في git — سيكسر update.bat"


def test_config_toml_is_gitignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "config.toml" in [line.strip() for line in ignored]


def test_example_config_exists_and_is_tracked():
    example = ROOT / "config.example.toml"
    assert example.exists(), "config.example.toml مفقود"
    text = example.read_text(encoding="utf-8")
    assert "[strategy]" in text and "[trade]" in text
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "config.example.toml"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, "config.example.toml يجب أن يكون مُتتبَّعاً"


def test_load_creates_config_from_example(tmp_path, monkeypatch):
    """إن غاب config.toml نُنسخ من المثال بدل العمل بإعدادات افتراضية صامتة."""
    example = tmp_path / "config.example.toml"
    example.write_text('[trade]\nqty_usdt = 77\n', encoding="utf-8")
    target = tmp_path / "config.toml"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", target)
    monkeypatch.setattr(config_module, "EXAMPLE_CONFIG_PATH", example)

    cfg = Config.load()
    assert target.exists()
    assert cfg.get("trade.qty_usdt") == 77          # من المثال
    assert cfg.get("strategy.timeframe") == "15m"   # والباقي من الافتراضي


def test_load_does_not_create_file_when_path_given(tmp_path, monkeypatch):
    """مسار صريح = لا نسخ (سلوك الاختبارات والسكربتات)."""
    example = tmp_path / "config.example.toml"
    example.write_text("[trade]\nqty_usdt = 77\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "EXAMPLE_CONFIG_PATH", example)

    cfg = Config.load(tmp_path / "missing.toml", tmp_path / "missing.env")
    assert not (tmp_path / "missing.toml").exists()
    assert cfg.get("trade.qty_usdt") == 50          # القيمة الافتراضية


def test_load_keeps_existing_config(tmp_path, monkeypatch):
    """لا نطغى على إعدادات المستخدم إن كان config.toml موجوداً."""
    example = tmp_path / "config.example.toml"
    example.write_text("[trade]\nqty_usdt = 77\n", encoding="utf-8")
    target = tmp_path / "config.toml"
    target.write_text("[trade]\nqty_usdt = 12\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", target)
    monkeypatch.setattr(config_module, "EXAMPLE_CONFIG_PATH", example)

    assert Config.load().get("trade.qty_usdt") == 12
