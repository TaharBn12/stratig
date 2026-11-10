"""اختبار سكربت التدقيق نفسه — يجب أن يبقى سليماً بعد أي تعديل.

يستدعي فحوصات التدقيق مباشرة (بلا عمليات خارجية) ليكون سريعاً وآمناً
داخل pytest — أما تشغيل الاختبارات من داخل التدقيق فله `--tests`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.audit as audit  # noqa: E402

ALL_CHECKS = (
    audit.audit_python,
    audit.audit_config_paths,
    audit.audit_set_keys,
    audit.audit_strategies,
    audit.audit_notebook_constants,
    audit.audit_timeframes,
    audit.audit_config_example,
    audit.audit_git,
    audit.audit_bat,
)


def test_every_audit_check_passes():
    """"التحقق من كامل الملفات" يجب أن ينتهي بلا أخطاء."""
    audit.problems.clear()
    audit.warnings.clear()
    for check in ALL_CHECKS:
        check()
    assert audit.problems == [], "\n".join(audit.problems)


def test_audit_detects_a_broken_notebook_constant(monkeypatch):
    """إن غيّر أحدهم ثابتاً من الدفتر يجب أن يفشل التدقيق (لا أن يمرّ بصمت)."""
    audit.problems.clear()
    audit.warnings.clear()

    def broken():
        audit.report(False, "ثابت مُخترَق", "EMA_SLOW يجب أن يبقى 50")

    for check in ALL_CHECKS:
        if check.__name__ != "audit_notebook_constants":
            monkeypatch.setattr(audit, check.__name__, lambda: None)
    monkeypatch.setattr(audit, "audit_notebook_constants", broken)
    assert audit.main([]) == 1
    assert any("ثابت مُخترَق" in p for p in audit.problems)


def test_audit_tests_section_lists_files():
    audit.problems.clear()
    audit.warnings.clear()
    audit.audit_tests()
    assert audit.problems == [] and audit.warnings == []
