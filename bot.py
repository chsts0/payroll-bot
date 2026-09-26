"""Telegram-бот: присылаешь таблицу или данные — получаешь расчётные листы и рассылаешь их сотрудникам."""
import asyncio
import logging
import os
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from card import COMPANY, money, render
from payroll import (KPI_PERCENT, POINTS, RATE, ROUND_TO, ParseError, find_period,
                     make_template, parse_table, parse_text)
from staff import Staff

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

TOKEN = os.environ["BOT_TOKEN"]
ALLOWED = [int(x) for x in os.getenv("ALLOWED_USERS", "").replace(" ", "").split(",") if x and x != "0"]
RUN_MINUTES = float(os.getenv("RUN_MINUTES", "0"))   # 0 = работать бесконечно
staff = Staff(ALLOWED[0]) if ALLOWED else None

HELP = (
    "<b>Таблицей:</b> пришли файл .xlsx или .csv (выгрузку из вашей таблицы). "
    "Беру последний период в таблице; другой — напиши в подписи к файлу, например <code>15.07-31.07</code>.\n\n"
    "<b>Вручную:</b> первая строка — период, дальше по строке на человека:\n"
    "<code>1.09 – 15.09\n"
    "Даша С 28 0\n"
    "Оля П 80 41700\n"
    "Оля В 10 0\n"
    "Василина В 70 42120 оф 13593</code>\n"
    "Формат: имя, точка, часы, продажи. Удержания в конце: <code>оф 13593</code>, <code>опц 500</code>.\n"
    "Один человек на нескольких точках — несколько строк, соберу в одну карточку.\n\n"
    "Точки: " + ", ".join(f"{c} ({v[0]})" for c, v in POINTS.items()) + "\n"
    f"Ставка при ручном вводе {RATE} ₽/ч, КПИ {KPI_PERCENT}% от продаж, к выплате округляется вверх до {ROUND_TO}.\n\n"
    "<b>Рассылка:</b> под карточками будет кнопка «Разослать».\n"
    "/staff — список сотрудников\n"
    "<code>/add Имя @username</code> — добавить (имя как в таблице)\n"
    "<code>/del Имя</code> — удалить\n"
    "Каждый сотрудник должен один раз написать боту /start, иначе Telegram не даст ему написать.\n\n"
    "/template — шаблон таблицы"
)


def is_admin(update: Update) -> bool:
    return bool(update.effective_user and update.effective_user.id in ALLOWED)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(update):
        if staff.register(user.username, update.effective_chat.id):
            await staff.save(context.bot)
        await update.message.reply_html(HELP)
        return
    if not ALLOWED:
        await update.message.reply_text(
            f"Бот ещё не настроен. Твой Telegram ID: {user.id}\n"
            "Добавь его в секрет ALLOWED_USERS на GitHub и перезапусти бота.")
        return
    name = staff.register(user.username, update.effective_chat.id)
    if name:
        await staff.save(context.bot)
        await update.message.reply_text(f"Привет, {name}! Сюда будут приходить твои расчётные листы {COMPANY}.")
        await context.bot.send_message(ALLOWED[0], f"✅ {name} (@{user.username}) подключился к рассылке")
    else:
        log.warning("Незнакомый пользователь %s @%s", user.id, user.username)
        await update.message.reply_text(
            "Этот бот присылает расчётные листы сотрудникам. Тебя пока нет в списке — "
            "напиши администратору, чтобы он добавил твой @username, и нажми /start ещё раз.")


async def template(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if is_admin(update):
        await update.message.reply_document(make_template(), filename="шаблон_выписки.xlsx")


async def cmd_staff(update: Update, _: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    lines = staff.lines()
    await update.message.reply_text("\n".join(lines) if lines else "Список пуст. Добавь: /add Имя @username")


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    args = context.args
    if len(args) < 2 or not args[-1].startswith("@"):
        await update.message.reply_html("Формат: <code>/add Имя @username</code>")
        return
    name = " ".join(args[:-1])
    staff.add(name, args[-1])
    await staff.save(context.bot)
    await update.message.reply_text(f"Добавил: {name} — {args[-1]}. Пусть напишет боту /start.")


async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    name = " ".join(context.args)
    if staff.remove(name):
        await staff.save(context.bot)
        await update.message.reply_text(f"Удалил: {name}")
    else:
        await update.message.reply_text(f"Не нашёл: {name}")


async def process(update: Update, context, period, people, errors, mismatches):
    msg = update.message
    if errors:
        await msg.reply_text("⚠️ Не смог разобрать:\n" + "\n".join(errors[:25]))
    if not people:
        if not errors:
            await msg.reply_html("Не нашёл данных.\n\n" + HELP)
        return
    if not period:
        await msg.reply_html("Укажи период, например первой строкой: <code>1.09 – 15.09</code>")
        return
    if mismatches:
        await msg.reply_text("⚠️ Не сходится с колонкой «к выплате» в таблице:\n"
                             + "\n".join(mismatches[:25]) + "\nНа карточках — мой расчёт.")

    items = []   # (name, file_id)
    cards = [(p, render(p, period)) for p in people]
    for i in range(0, len(cards), 10):
        chunk = cards[i:i + 10]
        if len(chunk) == 1:
            p, png = chunk[0]
            sent = [await msg.reply_photo(png, caption=p.name)]
        else:
            sent = await msg.reply_media_group([InputMediaPhoto(png, caption=p.name) for p, png in chunk])
        for (p, _), m in zip(chunk, sent):
            items.append((p.name, m.photo[-1].file_id))

    bid = uuid.uuid4().hex[:8]
    context.bot_data.setdefault("batches", {})[bid] = {"period": period, "items": items}
    total = sum(p.payout for p in people)
    ready = [n for n, _ in items if staff.chat_for(n)]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        f"\U0001F4E4 Разослать ({len(ready)} из {len(items)})", callback_data=f"ask:{bid}")]])
    await msg.reply_text(f"Готово, карточек: {len(people)} ({period})\nВсего к выплате: {money(total)}",
                         reply_markup=kb)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return await start(update, context)
    await process(update, context, *parse_text(update.message.text))


async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    doc = update.message.document
    try:
        data = bytes(await (await doc.get_file()).download_as_bytearray())
        want = find_period(update.message.caption or "")
        result = parse_table(doc.file_name or "", data, want)
    except ParseError as e:
        await update.message.reply_text(f"⚠️ {e}")
        return
    except Exception:
        log.exception("Ошибка чтения файла")
        await update.message.reply_text("⚠️ Не смог прочитать файл. Проверь, что это .xlsx или .csv")
        return
    await process(update, context, *result)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(update):
        return await q.answer()
    action, _, bid = q.data.partition(":")
    batch = context.bot_data.get("batches", {}).get(bid)
    if not batch:
        await q.answer("Бот перезапускался — пришли данные ещё раз", show_alert=True)
        return
    items = batch["items"]
    ready = [(n, f) for n, f in items if staff.chat_for(n)]
    missing = [n for n, _ in items if not staff.chat_for(n)]

    if action == "ask":
        await q.answer()
        text = f"Отправить расчётные листы за {batch['period']}: {len(ready)} чел.?"
        if missing:
            text += "\n\nНе получат (нет в /staff или не нажали /start):\n" + ", ".join(missing)
        kb = [[InlineKeyboardButton("✅ Да, отправить", callback_data=f"go:{bid}"),
               InlineKeyboardButton("Отмена", callback_data=f"no:{bid}")]] if ready else \
             [[InlineKeyboardButton("Понятно", callback_data=f"no:{bid}")]]
        await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    elif action == "no":
        await q.answer("Отменено")
        await q.message.edit_reply_markup(None)
    elif action == "go":
        await q.answer("Отправляю…")
        await q.message.edit_reply_markup(None)
        ok, fail = [], []
        for name, file_id in ready:
            try:
                await context.bot.send_photo(staff.chat_for(name), file_id,
                                             caption=f"Расчётный лист {COMPANY} за {batch['period']}")
                ok.append(name)
            except Exception as e:
                log.warning("Не отправилось %s: %s", name, e)
                fail.append(name)
            await asyncio.sleep(0.1)
        text = f"\U0001F4E8 Отправлено: {len(ok)}"
        if fail:
            text += "\nНе удалось (возможно, заблокировали бота): " + ", ".join(fail)
        if missing:
            text += "\nНе отправлено (нет в базе): " + ", ".join(missing)
        await q.message.reply_text(text)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка: %s", context.error)


async def post_init(app: Application):
    if staff:
        await staff.load(app.bot)
    if RUN_MINUTES > 0:
        log.info("Бот остановится через %s мин (следующий запуск подхватит)", RUN_MINUTES)
        asyncio.get_running_loop().call_later(RUN_MINUTES * 60, app.stop_running)


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("template", template))
    app.add_handler(CommandHandler("staff", cmd_staff))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("Бот запущен, админов: %d", len(ALLOWED))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
