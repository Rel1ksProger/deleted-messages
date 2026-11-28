# deleted_messages.py
# -*- coding: utf-8 -*-

__id__ = "deleted_messages"
__name__ = "Deleted Messages"
__description__ = "Просмотр удалённых сообщений текущего чата, кеш с лимитом, BottomSheet, Bulletins"
__author__ = "Rel1ksProger"
__version__ = "1.0.3"
__app_version__ = ">=13.1.1"
__sdk_version__ = ">=1.4.4.3"
__category__ = "chats"

import time
import datetime

from base_plugin import BasePlugin, MethodHook, HookResult
from android_utils import run_on_ui_thread
from client_utils import get_last_fragment
from ui.bulletin import BulletinHelper
from ui.settings import Header, Switch, Input, Text, Divider
from org.telegram.ui.ActionBar import BottomSheet, Theme
from org.telegram.messenger import AndroidUtilities
from android.widget import LinearLayout, TextView

# ----------------------------- хранилище -----------------------------
_cache = {}          # dialog_id -> list[dict]
_limit_per_chat = 100
_show_toast = True


def _add_to_cache(dialog_id, record):
    lst = _cache.setdefault(dialog_id, [])
    lst.insert(0, record)
    while len(lst) > _limit_per_chat:
        lst.pop()


def _determine_media_type(msg):
    if getattr(msg, "isSticker", False):
        return "STICKER"
    if getattr(msg, "isPhoto", False):
        return "PHOTO"
    if getattr(msg, "isVideo", False):
        return "VIDEO"
    if getattr(msg, "isVoice", False) or getattr(msg, "isMusic", False):
        return "AUDIO"
    if getattr(msg, "isDocument", False):
        return "DOCUMENT"
    if getattr(msg, "messageText", None):
        return "TEXT"
    return "OTHER"


class DeletedMessagesPlugin(BasePlugin):
    def on_plugin_load(self):
        self.logger.info("DeletedMessages loaded")

        # Xposed-хук на MessagesController.deleteMessages.
        # Используем MethodHook — стандартный способ для точечного перехвата.
        MessagesController = self.find_class(
            "org.telegram.messenger.MessagesController"
        )
        if MessagesController:
            self.add_hook(
                MessagesController.deleteMessages,
                self._on_delete_messages,
            )

    def _on_delete_messages(self, param):
        """MethodHook: before_hooked_method."""
        try:
            messages = param.args[0]  # ArrayList<MessageObject>
            if not messages:
                return

            dialog_id = messages[0].getDialogId()
            for msg in messages:
                record = {
                    "sender": msg.getSenderName() or "Неизвестный",
                    "time": time.time(),
                    "media": _determine_media_type(msg),
                    "preview": (msg.messageText or "")[:100],
                    "msg_id": msg.getId(),
                }
                _add_to_cache(dialog_id, record)

                if _show_toast:
                    run_on_ui_thread(
                        lambda r=record: self._show_bulletin(
                            f"Удалено: {r['sender']} · {r['media']}"
                        )
                    )
        except Exception as e:
            self.logger.exception("DeletedMessages hook error")

    def _show_bulletin(self, text):
        """Показывает нативное уведомление Telegram (Bulletin)."""
        try:
            fragment = get_last_fragment()
            if fragment:
                BulletinHelper.show_info(fragment, text)
        except Exception:
            self.logger.warning("Не удалось показать Bulletin: %s", text)

    # -------- меню и BottomSheet --------
    def create_menu_items(self):
        return [
            {
                "text": "Удалённые сообщения",
                "onClick": self._open_bottom_sheet,
            }
        ]

    def _open_bottom_sheet(self, fragment):
        dialog_id = self._current_dialog_id(fragment)
        if dialog_id is None:
            self.logger.warning("Не удалось определить ID текущего диалога")
            return
        records = _cache.get(dialog_id, [])
        self._build_bottom_sheet(fragment, dialog_id, records)

    def _current_dialog_id(self, fragment):
        try:
            return fragment.getDialogId()
        except Exception:
            return None

    def _build_bottom_sheet(self, fragment, dialog_id, records):
        ctx = fragment.getParentActivity()
        if not ctx:
            return

        sheet = BottomSheet(ctx, False, fragment.getResourceProvider())
        sheet.setApplyBottomPadding(False)
        sheet.setApplyTopPadding(False)
        sheet.fixNavigationBar(Theme.getColor(Theme.key_windowBackgroundWhite))

        container = LinearLayout(ctx)
        container.setOrientation(LinearLayout.VERTICAL)
        pad = AndroidUtilities.dp(16)
        container.setPadding(pad, pad, pad, pad)

        title = TextView(ctx)
        title.setText("Удалённые сообщения")
        title.setTextSize(18)
        container.addView(title)

        clear_btn = TextView(ctx)
        clear_btn.setText("🗑 Очистить этот чат")
        clear_btn.setTextColor(0xFFE53935)
        clear_btn.setOnClickListener(
            lambda v: (self._clear_chat(dialog_id), sheet.dismiss())
        )
        container.addView(clear_btn)

        if not records:
            empty = TextView(ctx)
            empty.setText("Нет удалённых сообщений")
            empty.setTextSize(16)
            container.addView(empty)
        else:
            for rec in records:
                container.addView(self._record_view(ctx, dialog_id, rec, sheet))

        sheet.setCustomView(container)
        sheet.show()

    def _record_view(self, ctx, dialog_id, rec, sheet):
        row = LinearLayout(ctx)
        row.setOrientation(LinearLayout.VERTICAL)
        row.setPadding(0, AndroidUtilities.dp(8), 0, AndroidUtilities.dp(8))

        dt = datetime.datetime.fromtimestamp(rec["time"]).strftime("%H:%M:%S")
        header = TextView(ctx)
        header.setText(f"{rec['sender']}  •  {dt}  •  {rec['media']}")
        header.setTextSize(14)
        row.addView(header)

        if rec.get("preview"):
            preview = TextView(ctx)
            preview.setText(rec["preview"])
            preview.setTextSize(13)
            row.addView(preview)

        del_btn = TextView(ctx)
        del_btn.setText("✕ Удалить из кеша")
        del_btn.setTextSize(12)
        del_btn.setTextColor(0xFF757575)
        del_btn.setOnClickListener(
            lambda v: (
                _cache.get(dialog_id, []).remove(rec)
                if rec in _cache.get(dialog_id, [])
                else None,
                sheet.dismiss(),
            )
        )
        row.addView(del_btn)
        return row

    def _clear_chat(self, dialog_id):
        _cache.pop(dialog_id, None)

    def clear_all(self):
        _cache.clear()

    # -------- настройки (ui.settings) --------
    def create_settings(self):
        return [
            Header(text="Deleted Messages"),
            Switch(
                key="show_toast",
                text="Уведомление при удалении",
                default=True,
                on_change=self._set_toast,
            ),
            Input(
                key="limit_per_chat",
                text="Лимит сообщений на чат",
                default="100",
                on_change=self._set_limit,
            ),
            Divider(),
            Text(text="Кеш очищается при выгрузке плагина."),
        ]

    def _set_toast(self, value):
        global _show_toast
        _show_toast = bool(value)

    def _set_limit(self, value):
        global _limit_per_chat
        try:
            _limit_per_chat = max(10, min(1000, int(value)))
        except (ValueError, TypeError):
            _limit_per_chat = 100

    def on_plugin_unload(self):
        self.clear_all()
        self.logger.info("DeletedMessages unloaded, cache cleared")