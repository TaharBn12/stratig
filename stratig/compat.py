"""حماية من مكتبات التشفير المترجَمة (pycryptodome).

مكتبتا Binance و Bybit تستوردان `Crypto` (pycryptodome) عند التحميل،
لكنهما تستخدمانها **فقط** مع مفاتيح RSA/Ed25519 — أما المفاتيح العادية
(api_key / api_secret) فتستخدم HMAC من المكتبة القياسية.

لذلك: إن تعذّر تحميل pycryptodome (مكتبة C لا تعمل على الجهاز)،
نضع بديلاً وهمياً يسمح بتحميل المكتبة والعمل بشكل طبيعي.
"""
from __future__ import annotations

import logging
import sys
import types

log = logging.getLogger(__name__)

_CRYPTO_NAMES = ("RSA", "SHA256", "pkcs1_15", "PKCS1_v1_5", "DSS", "Ed25519")


def _build_stub() -> None:
    def make(name: str, **attrs) -> types.ModuleType:
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    crypto = make("Crypto")
    crypto.__path__ = []  # نوع حزمة حتى تعمل الاستيرادات الفرعية

    public_key = make("Crypto.PublicKey", RSA=object)
    hashing = make("Crypto.Hash", SHA256=object)
    signature = make(
        "Crypto.Signature",
        pkcs1_15=object,
        PKCS1_v1_5=object,
        DSS=object,
    )
    crypto.PublicKey = public_key  # type: ignore[attr-defined]
    crypto.Hash = hashing  # type: ignore[attr-defined]
    crypto.Signature = signature  # type: ignore[attr-defined]

    # وحدات فرعية قد تطلبها pycryptodome نفسها
    make("Crypto.Util", number=object)
    make("Crypto.Util.number")
    make("Crypto.Math", Numbers=object)
    make("Crypto.Random")


def ensure_crypto_stub() -> bool:
    """يضع بديلاً وهمياً لـ Crypto إن لم تكن متاحة. يرجع True إن تم وضع البديل."""
    if "Crypto" in sys.modules:
        return False
    try:
        import Crypto  # noqa: F401
        return False
    except Exception as err:
        _build_stub()
        log.warning(
            "تعذّر تحميل مكتبة التشفير pycryptodome (%s) — تم استخدام بديل وهمي. "
            "هذا لا يؤثر على العمل لأن المفاتيح العادية تستخدم HMAC.",
            err,
        )
        return True


def import_module_safely(module_path: str, attribute: str):
    """يستورد `attribute` من `module_path` مع تخطّي مشاكل Crypto."""
    from importlib import import_module

    try:
        return getattr(import_module(module_path), attribute)
    except Exception as err:
        failing = str(getattr(err, "name", "") or "")
        related = (
            failing.startswith("Crypto")
            or "Crypto" in str(err)
            or "pycryptodome" in str(err).lower()
        )
        if not related:
            raise
        ensure_crypto_stub()
        return getattr(import_module(module_path), attribute)
