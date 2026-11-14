"""База сотрудников для рассылки.

Хранится зашифрованным файлом data/staff.enc в этом же репозитории
(ключ выводится из BOT_TOKEN, так что в публичном репо данные не прочитать).
Бот сам коммитит файл через GITHUB_TOKEN, поэтому база переживает перезапуски.
Старый вариант (закреплённое сообщение в чате админа) читается один раз для переноса.

Запись: имя (как в таблице) -> {"n": имя, "u": username без @, "id": chat_id или None}.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os

import httpx
from cryptography.fernet import Fernet, InvalidToken

from payroll import norm_name

log = logging.getLogger("staff")
MARK = "\U0001F4C7 База сотрудников для рассылки (не открепляй это сообщение)"
FILE = "data/staff.enc"


def _fernet():
    key = hashlib.sha256(("payroll-staff:" + os.environ["BOT_TOKEN"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class Staff:
    def __init__(self, admin_id: int):
        self.admin_id = admin_id
        self.data = {}
        self.sha = None
        self.loaded = False          # база прочитана (или точно пустая) — можно сохранять
        self.lock = asyncio.Lock()
        self.repo = os.getenv("GITHUB_REPOSITORY")
        self.token = os.getenv("GITHUB_TOKEN")
        self.branch = os.getenv("GITHUB_REF_NAME", "main")

    # ---------- GitHub ----------
    def _url(self):
        return f"https://api.github.com/repos/{self.repo}/contents/{FILE}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    async def _gh_read(self):
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(self._url(), headers=self._headers(), params={"ref": self.branch})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        j = r.json()
        self.sha = j["sha"]
        return base64.b64decode(j["content"])

    async def _gh_write(self, blob: bytes):
        body = {"message": "staff: update", "content": base64.b64encode(blob).decode(), "branch": self.branch}
        async with httpx.AsyncClient(timeout=30) as c:
            for attempt in range(3):
                if self.sha:
                    body["sha"] = self.sha
                r = await c.put(self._url(), headers=self._headers(), json=body)
                if r.status_code in (409, 422) and attempt < 2:      # файл поменялся — берём свежий sha
                    g = await c.get(self._url(), headers=self._headers(), params={"ref": self.branch})
                    self.sha = g.json().get("sha") if g.status_code == 200 else None
                    continue
                r.raise_for_status()
                self.sha = r.json()["content"]["sha"]
                return

    # ---------- загрузка / сохранение ----------
    async def load(self, bot):
        source = None
        if self.repo and self.token:
            try:
                blob = await self._gh_read()
                if blob is not None:
                    self.data = json.loads(_fernet().decrypt(blob))
                    source = "github"
                self.loaded = True
            except (InvalidToken, Exception) as e:
                log.error("Не смог прочитать базу из репозитория: %s", e)
        else:
            log.warning("Нет GITHUB_TOKEN/GITHUB_REPOSITORY — база не будет сохраняться между перезапусками")
            self.loaded = True

        if source is None and self.loaded:
            # перенос из старого закреплённого сообщения
            try:
                chat = await bot.get_chat(self.admin_id)
                pm = chat.pinned_message
                if pm and pm.text and pm.text.startswith(MARK):
                    self.data = json.loads(pm.text.split("\n", 1)[1])
                    source = "pinned"
            except Exception as e:
                log.warning("Старую базу из закрепа не прочитал: %s", e)

        changed = source == "pinned"
        if source is None and self.loaded:
            seed = os.getenv("STAFF_SEED", "")
            for part in filter(None, (p.strip() for p in seed.split(";"))):
                name, _, user = part.partition("=")
                if name.strip():
                    self.data[norm_name(name)] = {"n": name.strip(), "u": user.strip().lstrip("@").lower(), "id": None}
                    changed = True
            source = "seed"
        if changed:
            await self.save(bot)
        log.info("База сотрудников: %d чел., источник: %s", len(self.data), source or "не загружена!")

    async def save(self, bot=None):
        if not self.loaded:
            log.error("База не загрузилась при старте — не сохраняю, чтобы не затереть")
            return
        if not (self.repo and self.token):
            return
        async with self.lock:
            blob = _fernet().encrypt(json.dumps(self.data, ensure_ascii=False).encode())
            try:
                await self._gh_write(blob)
            except Exception as e:
                log.error("Не смог сохранить базу: %s", e)

    # ---------- операции ----------
    def add(self, name, username):
        key = norm_name(name)
        old = self.data.get(key, {})
        u = username.lstrip("@").lower()
        city = old.get("c")
        self.data[key] = {"n": " ".join(name.split()), "u": u,
                          "id": old.get("id") if old.get("u") == u else None}
        if city:
            self.data[key]["c"] = city

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
