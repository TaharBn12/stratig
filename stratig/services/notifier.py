"""طبقة الإشعارات: تعزل البوت عن تليجرام (قابلة للاستبدال أو الاختبار)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

log = logging.getLogger(__name__)


@dataclass
class Button:
    """زر داخل الرسالة — مستقل عن مكتبة تليجرام."""
    text: str
    data: str


@dataclass
class MessageRef:
    chat_id: int = 0
    message_id: int = 0


@dataclass
class Notifier:
    """واجهة مجرّدة: تُستخدم أيضاً في الاختبارات (تطبع بدل الإرسال)."""
    chat_ids: list = field(default_factory=list)

    async def send(
        self,
        text: str,
        buttons: Sequence[Sequence[Button]] | None = None,
        chat_id: Optional[int] = None,
    ) -> MessageRef | None:
        print(text)
        return MessageRef()

    async def edit(
        self,
        ref: MessageRef | None,
        text: str,
        buttons: Sequence[Sequence[Button]] | None = None,
    ) -> None:
        print(text)


class TelegramNotifier(Notifier):
    """يرسل إلى تليجرام عبر python-telegram-bot."""

    def __init__(self, bot, chat_ids: Iterable[int]):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        self.bot = bot
        self.chat_ids = list(chat_ids)
        self._btn = InlineKeyboardButton
        self._markup = InlineKeyboardMarkup

    def _keyboard(self, buttons):
        if not buttons:
            return None
        return self._markup(
            [[self._btn(text=b.text, callback_data=b.data) for b in row] for row in buttons]
        )

    async def send(self, text, buttons=None, chat_id=None):
        from telegram.constants import ParseMode
        from telegram.error import TelegramError

        targets = [chat_id] if chat_id else self.chat_ids
        if not targets:
            log.warning("لا يوجد chat_id لإرسال الرسالة")
            return None
        ref: MessageRef | None = None
        for cid in targets:
            try:
                msg = await self.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._keyboard(buttons),
                    disable_web_page_preview=True,
                )
                ref = MessageRef(chat_id=msg.chat_id, message_id=msg.message_id)
            except TelegramError as err:
                log.error("فشل الإرسال إلى %s: %s", cid, err)
        return ref

    async def edit(self, ref, text, buttons=None):
        from telegram.constants import ParseMode
        from telegram.error import TelegramError

        if not ref or not ref.message_id:
            return
        try:
            await self.bot.edit_message_text(
                chat_id=ref.chat_id,
                message_id=ref.message_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=self._keyboard(buttons),
                disable_web_page_preview=True,
            )
        except TelegramError as err:
            log.warning("تعذّر تعديل الرسالة: %s", err)
