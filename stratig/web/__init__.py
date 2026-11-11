"""لوحة تحكم ستراتيج — واجهة محلية (خادم خفيف) + رفع اختياري إلى Supabase.

الهدف: ترى أداء البوت من المتصفح أو الهاتف بدل الاعتماد على تليجرام وحده:
  • منحنى الرصيد التراكمي (يكشف متى تتوقف الاستراتيجية عن العمل)
  • حالة إدارة المخاطر: هل التداول مسموح الآن؟ ولماذا؟
  • الصفقات المفتوحة مع الوقف والهدف

ثلاثة أوضاع، ولقطة واحدة موحّدة:
  build_snapshot(trader, cfg)  →  اللوحة المحلية  ·  Supabase  ·  Vercel
"""
from .server import Dashboard
from .snapshot import build_snapshot
from .supabase import SupabaseSync

__all__ = ["Dashboard", "build_snapshot", "SupabaseSync"]
