"""База сотрудников для рассылки.

Хранится в закреплённом сообщении бота в чате с админом, чтобы переживать
перезапуски без сервера и без публикации данных в репозиторий.
Запись: имя (как в таблице) -> {"u": username без @, "id": chat_id или None}.
"""
import json
import logging
import os

from payroll import norm_name

log = logging.getLogger("staff")
MARK = "\U0001F4C7 База сотрудников для рассылки (не открепляй это сообщение)"


class Staff:
    def __init__(self, admin_id: int):
        self.admin_id = admin_id
        self.data = {}          # norm_name -> {"n": имя, "u": username, "id": chat_id}
        self.msg_id = None

    async def load(self, bot):
        try:
            chat = await bot.get_chat(self.admin_id)
            pm = chat.pinned_message
            if pm and pm.text and pm.text.startswith(MARK):
                self.data = json.loads(pm.text.split("\n", 1)[1])
                self.msg_id = pm.message_id
        except Exception as e:
            log.warning("Не смог загрузить базу: %s", e)
        seed = os.getenv("STAFF_SEED", "")
        changed = False
        for part in filter(None, (p.strip() for p in seed.split(";"))):
            name, _, user = part.partition("=")
            if name.strip() and norm_name(name) not in self.data:
                self.data[norm_name(name)] = {"n": name.strip(), "u": user.strip().lstrip("@").lower(), "id": None}
                changed = True
        if changed:
            await self.save(bot)
        log.info("Сотрудников в базе: %d", len(self.data))

    async def save(self, bot):
        text = MARK + "\n" + json.dumps(self.data, ensure_ascii=False)
        if self.msg_id:
            try:
                await bot.edit_message_text(text, chat_id=self.admin_id, message_id=self.msg_id)
                return
            except Exception as e:
                if "not modified" in str(e).lower():
                    return
                log.warning("Не смог обновить базу, создаю заново: %s", e)
        m = await bot.send_message(self.admin_id, text, disable_notification=True)
        await bot.pin_chat_message(self.admin_id, m.message_id, disable_notification=True)
        self.msg_id = m.message_id

    def add(self, name, username):
        key = norm_name(name)
        old = self.data.get(key, {})
        u = username.lstrip("@").lower()
        self.data[key] = {"n": " ".join(name.split()), "u": u, "id": old.get("id") if old.get("u") == u else None}

    def remove(self, name):
        return self.data.pop(norm_name(name), None) is not None

    def register(self, username, chat_id):
        """Сотрудник нажал /start. Возвращает имя или None."""
        if not username:
            return None
        u = username.lower()
        for rec in self.data.values():
            if rec["u"] == u:
                rec["id"] = chat_id
                return rec["n"]
        return None

    def chat_for(self, name):
        rec = self.data.get(norm_name(name))
        return rec and rec.get("id")

    def lines(self):
        out = []
        for rec in sorted(self.data.values(), key=lambda r: r["n"].lower()):
            mark = "✅" if rec.get("id") else "⏳ не нажал(а) /start"
            out.append(f"{rec['n']} — @{rec['u']} {mark}")
        return out
