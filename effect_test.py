"""Временный тест: шлёт первому админу пробный расчётный лист с конфетти. Удалить после проверки."""
import asyncio
import logging

from telegram import Bot

import bot
from card import render
from payroll import Entry, Person

logging.basicConfig(level=logging.INFO)


async def main():
    p = Person("Тест Тестович", [Entry("С", hours=100, sales=50000)])
    png = render(p, "тест")
    async with Bot(bot.TOKEN) as b:
        msg = await bot.send_payslip(b, bot.ALLOWED[0], png, "тест (проверка конфетти)")
        print("effect_id в ответе:", msg.effect_id)
        who = {630410528: "Стас", 419070456: "@shrshnkt"}.get(msg.chat.id, "кто-то другой")
        print("Получатель:", who)
        if msg.effect_id != bot.CONFETTI:
            raise SystemExit("Эффект не применился, ушло без конфетти")
        print("OK: лист ушёл с конфетти")


asyncio.run(main())
