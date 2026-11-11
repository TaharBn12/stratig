"""لوحة التحكم — وضع القراءة من القرص (بلا منصة، بلا مفاتيح).

    python scripts/dashboard.py
    python scripts/dashboard.py --port 8080 --token سري

تقرأ سجل الصفقات (risk.journal_path) والإعدادات، فتعمل **حتى والبوت موقف**.
هذا هو الوضع المفيد للإجابة على سؤال «هل استراتيجيتي رابحة فعلاً؟».
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stratig.config import Config, PROJECT_ROOT   # noqa: E402
from stratig.web.server import Dashboard          # noqa: E402
from stratig.web.snapshot import build_snapshot   # noqa: E402

log = logging.getLogger("stratig")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="لوحة تحكم ستراتيج")
    parser.add_argument("--config", default=os.getenv("STRATIG_CONFIG", "config.toml"))
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--once", action="store_true",
                        help="اطبع اللقطة كـ JSON ثم اخرج (بلا خادم)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")

    config = Config.load(args.config, os.getenv("STRATIG_ENV", ".env"))
    page = Path(PROJECT_ROOT) / "dashboard" / "index.html"

    def snapshot() -> dict:
        return build_snapshot(config=config,
                              bot_id=str(config.get("supabase.bot_id", "default")))

    if args.once:
        import json
        print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
        return 0

    host = args.host or str(config.get("web.host", "0.0.0.0"))
    port = args.port or int(config.get("web.port", 8000))
    token = args.token or str(config.get("web.token", "") or "")

    dash = Dashboard(snapshot, host=host, port=port, token=token)
    dash.page = page
    # نفس السلوك على Vercel: المتصفح يقرأ Supabase مباشرة. نُرسل المفتاح
    # القابل للنشر فقط، فيبقى مفتاح الكتابة السرّي داخل الخدمة.
    dash.public_config = {
        "url": str(config.get("supabase.url", "") or ""),
        "anon_key": str(config.get("supabase.anon_key", "") or ""),
        "bot_id": str(config.get("supabase.bot_id", "default") or "default"),
    }
    if not dash.start():
        print(f"❌ تعذّر تشغيل الخادم على {host}:{port} — المنفذ مشغول؟")
        return 1

    stats = snapshot().get("stats", {})
    print(f"\n  لوحة التحكم تعمل:  {dash.url}")
    print(f"  الصفقات المسجّلة: {stats.get('count', 0)} · "
          f"صافي الربح: {stats.get('total_pnl', 0):+.2f} USDT · "
          f"التوقع: {stats.get('expectancy_r', 0):+.3f}R")
    print("  أوقفها بـ Ctrl+C\n")
    try:
        dash.thread.join()          # type: ignore[union-attr]
    except KeyboardInterrupt:
        print("\nتم الإيقاف.")
        dash.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
