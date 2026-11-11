// وظيفة Vercel: تُمرّر إعدادات Supabase إلى اللوحة بغير وضعها في المستودع.
// (مفتاح Supabase القابل للنشر مبني ليكون عامّاً، والحماية الحقيقية هي RLS،
//  لكن إبقاؤه في متغير بيئة أفضل من تثبيته في الكود.)
export default function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.status(200).json({
    url: process.env.SUPABASE_URL || "",
    key: process.env.SUPABASE_ANON_KEY || "",
    botId: process.env.BOT_ID || "default",
  });
}
