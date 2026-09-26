"""Telegram-бот: присылаешь данные — получаешь карточки выписки."""
import asyncio
import logging
import os

from telegram import InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from card import money, render
from payroll import KPI_PERCENT, RATE, ParseError, make_template, parse_table, parse_text


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

TOKEN = os.environ["BOT_TOKEN"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x and x != "0"}
RUN_MINUTES = float(os.getenv("RUN_MINUTES", "0"))   # 0 = работать бесконечно

HELP = (
    "Пришли данные \u2014 я сделаю карточки выписки.\n\n"
    "<b>Текстом</b> (первая строка \u2014 период, дальше по строке на человека):\n"
    "<code>1.08 \u2013 14.08\n"
    "Стас 55 66300\n"
    "Аня 48 52000</code>\n"
    "Формат: имя, часы, продажи.\n\n"
    "<b>Файлом</b> Excel/CSV с колонками Имя, Часы, Продажи. "
    "Период \u2014 в подписи к файлу или в ячейке \u00abПериод\u00bb. Шаблон: /template\n\n"
    f"Ставка {RATE} \u20bd/ч, КПИ = {KPI_PERCENT}% от продаж, "
    "\u00abк выплате\u00bb округляется вверх до сотни."
)


def allowed(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ALLOWED


async def guard(update: Update) -> bool:
    if allowed(update):
        return True
    uid = update.effective_user.id if update.effective_user else "?"
    log.warning("Отказано пользователю %s", uid)
    if not ALLOWED:
        await update.message.reply_text(
            f"Бот ещё не настроен. Твой Telegram ID: {uid}\n"
            "Добавь его в секрет ALLOWED_USERS на GitHub и перезапусти бота."
        )
    return False


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        await update.message.reply_html(HELP)


async def template(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if await guard(update):
        await update.message.reply_document(make_template(), filename="шаблон_выписки.xlsx",
                                            caption="Заполни и пришли обратно")


async def process(update: Update, period, rows, errors):
    msg = update.message
    if errors:
        await msg.reply_text("⚠️ Не смог разобрать:\n" + "\n".join(errors[:20]))
    if not rows:
        if not errors:
            await msg.reply_html("Не нашёл данных.\n\n" + HELP)
        return
    if not period:
        await msg.reply_html("Укажи период, например первой строкой: <code>1.08 – 14.08</code>")
        return

    images = [(r, render(r, period)) for r in rows]
    for i in range(0, len(images), 10):
        chunk = images[i:i + 10]
        if len(chunk) == 1:
            r, png = chunk[0]
            await msg.reply_photo(png, caption=r.name)
        else:
            await msg.reply_media_group([InputMediaPhoto(png, caption=r.name) for r, png in chunk])

    total = sum(r.payout for r in rows)
    await msg.reply_text(f"Готово, карточек: {len(rows)} ({period})\nВсего к выплате: {money(total)}")


async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    period, rows, errors = parse_text(update.message.text)
    await process(update, period, rows, errors)


async def on_file(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    doc = update.message.document
    try:
        data = bytes(await (await doc.get_file()).download_as_bytearray())
        period, rows, errors = parse_table(doc.file_name or "", data)
    except ParseError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    except Exception:
        log.exception("Ошибка чтения файла")
        await update.message.reply_text("⚠️ Не смог прочитать файл. Проверь, что это .xlsx или .csv")
        return
    from payroll import find_period
    period = find_period(update.message.caption or "") or period
    await process(update, period, rows, errors)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка: %s", context.error)


async def post_init(app: Application):
    if RUN_MINUTES > 0:
        log.info("Бот остановится через %s мин (следующий запуск подхватит)", RUN_MINUTES)
        asyncio.get_running_loop().call_later(RUN_MINUTES * 60, app.stop_running)


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("template", template))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("Бот запущен, доступ: %s", ALLOWED or "никому (нужен ALLOWED_USERS)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
