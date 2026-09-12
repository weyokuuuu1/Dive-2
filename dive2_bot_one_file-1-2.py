import os
import asyncio
import sqlite3
import logging
from datetime import datetime
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

# Зависимость: python-telegram-bot
# Если хостинг поддерживает установку пакетов, установи: pip install python-telegram-bot

# =========================
# НАСТРОЙКИ
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 5281171325
DB_NAME = "dive2.db"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip() or "dive2-webhook-secret-change-me"

# Для регистрации анкеты
NAME, AGE, CITY, ABOUT, PHOTO = range(5)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# =========================
# БАЗА ДАННЫХ
# =========================
def connect():
    con = sqlite3.connect(DB_NAME)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = connect()

    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            city TEXT NOT NULL,
            about TEXT DEFAULT '',
            photo TEXT NOT NULL,
            gender TEXT DEFAULT '',
            search_gender TEXT DEFAULT '',
            is_banned INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            user_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, target_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS skips (
            user_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, target_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS blocks (
            user_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, target_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_id INTEGER NOT NULL,
            to_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    con.close()


# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================
def get_user(user_id):
    con = connect()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row


def is_banned(user_id):
    row = get_user(user_id)
    return bool(row and row["is_banned"])


def profile_text(user):
    return (
        f"👤 {user['name']}, {user['age']}\n"
        f"📍 {user['city']}\n\n"
        f"💬 {user['about'] or 'О себе ничего не указано.'}"
    )


async def send_menu(update: Update):
    text = (
        "🌊 <b>ДАЙВ 2</b>\n\n"
        "Знакомства, лайки и взаимные симпатии.\n\n"
        "Выбери действие:"
    )

    keyboard = [
        [InlineKeyboardButton("🔎 Смотреть анкеты", callback_data="browse")],
        [InlineKeyboardButton("❤️ Мои лайки", callback_data="mylikes")],
        [InlineKeyboardButton("💕 Взаимные симпатии", callback_data="matches")],
        [InlineKeyboardButton("👤 Моя анкета", callback_data="profile")],
        [InlineKeyboardButton("✏️ Изменить анкету", callback_data="edit")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]

    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=markup, parse_mode="HTML"
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=markup, parse_mode="HTML"
            )
    elif update.message:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="HTML"
        )


async def banned_guard(update):
    uid = update.effective_user.id
    if is_banned(uid):
        if update.callback_query:
            await update.callback_query.answer("🚫 Вы заблокированы.", show_alert=True)
        elif update.message:
            await update.message.reply_text("🚫 Ваш аккаунт заблокирован.")
        return True
    return False


# =========================
# РЕГИСТРАЦИЯ
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await banned_guard(update):
        return ConversationHandler.END

    uid = update.effective_user.id
    user = get_user(uid)

    if user:
        await send_menu(update)
        return ConversationHandler.END

    context.user_data.clear()

    await update.message.reply_text(
        "👋 Добро пожаловать в <b>Дайв 2</b>!\n\n"
        "Давай создадим твою анкету.\n\n"
        "Как тебя зовут?",
        parse_mode="HTML"
    )
    return NAME


async def get_name(update, context):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 40:
        await update.message.reply_text("Имя должно быть от 2 до 40 символов.")
        return NAME

    context.user_data["name"] = name
    await update.message.reply_text("Сколько тебе лет?")
    return AGE


async def get_age(update, context):
    try:
        age = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введи возраст числом, например: 20")
        return AGE

    if age < 18 or age > 100:
        await update.message.reply_text("Возраст должен быть от 18 до 100 лет.")
        return AGE

    context.user_data["age"] = age
    await update.message.reply_text("В каком городе ты живёшь?")
    return CITY


async def get_city(update, context):
    city = update.message.text.strip()
    if len(city) < 2 or len(city) > 60:
        await update.message.reply_text("Напиши нормальное название города.")
        return CITY

    context.user_data["city"] = city
    await update.message.reply_text(
        "Расскажи немного о себе.\n"
        "Можно написать о характере, интересах или хобби."
    )
    return ABOUT


async def get_about(update, context):
    about = update.message.text.strip()
    if len(about) > 500:
        await update.message.reply_text("Описание максимум 500 символов.")
        return ABOUT

    context.user_data["about"] = about
    await update.message.reply_text(
        "📸 Теперь отправь свою фотографию."
    )
    return PHOTO


async def get_photo(update, context):
    if not update.message.photo:
        await update.message.reply_text("Отправь именно фотографию 📸")
        return PHOTO

    photo_id = update.message.photo[-1].file_id
    tg_user = update.effective_user
    d = context.user_data

    con = connect()
    con.execute("""
        INSERT OR REPLACE INTO users
        (id, username, name, age, city, about, photo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        tg_user.id,
        tg_user.username or "",
        d["name"],
        d["age"],
        d["city"],
        d["about"],
        photo_id
    ))
    con.commit()
    con.close()

    await update.message.reply_text(
        "✅ <b>Анкета готова!</b>\n\n"
        "Теперь можешь смотреть анкеты и ставить лайки.",
        parse_mode="HTML"
    )
    await send_menu(update)
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.clear()
    await update.message.reply_text("❌ Создание анкеты отменено.")
    return ConversationHandler.END


# =========================
# ПРОСМОТР АНКЕТ
# =========================
def get_next_profile(uid):
    con = connect()

    row = con.execute("""
        SELECT u.*
        FROM users u
        WHERE u.id != ?
          AND u.is_banned = 0
          AND u.id NOT IN (
              SELECT target_id FROM likes WHERE user_id=?
          )
          AND u.id NOT IN (
              SELECT target_id FROM skips WHERE user_id=?
          )
          AND u.id NOT IN (
              SELECT target_id FROM blocks WHERE user_id=?
          )
          AND u.id NOT IN (
              SELECT user_id FROM blocks WHERE target_id=?
          )
        ORDER BY RANDOM()
        LIMIT 1
    """, (uid, uid, uid, uid, uid)).fetchone()

    con.close()
    return row


async def show_next_profile(update, context):
    uid = update.effective_user.id
    user = get_next_profile(uid)

    if not user:
        if update.callback_query:
            await update.callback_query.message.reply_text(
                "😔 Новых анкет пока нет.\nПопробуй позже."
            )
        else:
            await update.message.reply_text("😔 Новых анкет пока нет.")
        return

    context.user_data["current_profile"] = user["id"]

    keyboard = [
        [
            InlineKeyboardButton(
                "❤️ Лайк", callback_data=f"like:{user['id']}"
            ),
            InlineKeyboardButton(
                "❌ Пропуск", callback_data=f"skip:{user['id']}"
            )
        ],
        [
            InlineKeyboardButton(
                "🚫 Заблокировать", callback_data=f"block:{user['id']}"
            ),
            InlineKeyboardButton(
                "⚠️ Пожаловаться", callback_data=f"report:{user['id']}"
            )
        ],
        [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
    ]

    await update.callback_query.message.reply_photo(
        photo=user["photo"],
        caption=profile_text(user),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def browse(update, context):
    await update.callback_query.answer()
    if await banned_guard(update):
        return
    await show_next_profile(update, context)


# =========================
# ЛАЙК / ПРОПУСК / БЛОК
# =========================
async def profile_action(update, context):
    q = update.callback_query
    await q.answer()
    if await banned_guard(update):
        return

    action, target_str = q.data.split(":")
    target = int(target_str)
    uid = q.from_user.id

    if uid == target:
        return

    con = connect()

    if action == "like":
        con.execute(
            "INSERT OR IGNORE INTO likes(user_id,target_id) VALUES(?,?)",
            (uid, target)
        )

        mutual = con.execute("""
            SELECT 1 FROM likes
            WHERE user_id=? AND target_id=?
        """, (target, uid)).fetchone()

        con.commit()

        if mutual:
            target_user = con.execute(
                "SELECT name FROM users WHERE id=?", (target,)
            ).fetchone()
            my_user = con.execute(
                "SELECT name FROM users WHERE id=?", (uid,)
            ).fetchone()

            if target_user:
                await q.message.reply_text(
                    f"💕 <b>Мэтч!</b>\n\n"
                    f"У вас взаимная симпатия с {target_user['name']}!\n"
                    f"Теперь можно написать друг другу.",
                    parse_mode="HTML"
                )

                try:
                    await context.bot.send_message(
                        target,
                        f"💕 <b>Мэтч!</b>\n\n"
                        f"{my_user['name']} тоже поставил(а) тебе лайк!\n"
                        f"Можете начать общение.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

        else:
            await q.message.reply_text("❤️ Лайк отправлен!")

    elif action == "skip":
        con.execute(
            "INSERT OR IGNORE INTO skips(user_id,target_id) VALUES(?,?)",
            (uid, target)
        )
        con.commit()
        await q.message.reply_text("❌ Пропущено.")

    elif action == "block":
        con.execute(
            "INSERT OR IGNORE INTO blocks(user_id,target_id) VALUES(?,?)",
            (uid, target)
        )
        con.commit()
        await q.message.reply_text("🚫 Пользователь заблокирован.")

    elif action == "report":
        con.execute(
            "INSERT INTO reports(reporter_id,target_id,reason) VALUES(?,?,?)",
            (uid, target, "Жалоба из анкеты")
        )
        con.commit()

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"⚠️ <b>Новая жалоба</b>\n\n"
                f"От: <code>{uid}</code>\n"
                f"На: <code>{target}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

        await q.message.reply_text(
            "⚠️ Жалоба отправлена администрации."
        )

    con.close()

    # Показываем следующую анкету
    await show_next_profile(update, context)


# =========================
# МОИ ЛАЙКИ / МЭТЧИ
# =========================
async def my_likes(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    con = connect()

    rows = con.execute("""
        SELECT u.name, u.age, u.city
        FROM users u
        JOIN likes l ON l.target_id=u.id
        WHERE l.user_id=?
        ORDER BY l.created_at DESC
        LIMIT 20
    """, (uid,)).fetchall()

    con.close()

    if not rows:
        text = "❤️ Ты пока никого не лайкал(а)."
    else:
        text = "❤️ <b>Твои лайки:</b>\n\n"
        text += "\n".join(
            f"• {r['name']}, {r['age']} — {r['city']}" for r in rows
        )

    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
        ])
    )


async def matches(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    con = connect()

    rows = con.execute("""
        SELECT u.name, u.age, u.city
        FROM users u
        JOIN likes a ON a.target_id=u.id AND a.user_id=?
        JOIN likes b ON b.user_id=u.id AND b.target_id=?
        WHERE u.is_banned=0
        ORDER BY u.name
    """, (uid, uid)).fetchall()

    con.close()

    if not rows:
        text = "💕 Взаимных симпатий пока нет."
    else:
        text = "💕 <b>Ваши взаимные симпатии:</b>\n\n"
        text += "\n".join(
            f"• {r['name']}, {r['age']} — {r['city']}" for r in rows
        )

    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
        ])
    )


# =========================
# МОЯ АНКЕТА
# =========================
async def show_profile(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    user = get_user(uid)

    if not user:
        await q.edit_message_text(
            "Анкета не найдена. Используй /start."
        )
        return

    keyboard = [[
        InlineKeyboardButton("✏️ Изменить", callback_data="edit"),
        InlineKeyboardButton("🗑 Удалить", callback_data="delete_confirm")
    ], [
        InlineKeyboardButton("⬅️ Меню", callback_data="menu")
    ]]

    await q.message.reply_photo(
        photo=user["photo"],
        caption=profile_text(user),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# УДАЛЕНИЕ
# =========================
async def delete_confirm(update, context):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "🗑 Точно удалить анкету?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Да, удалить", callback_data="delete_yes"),
                InlineKeyboardButton("❌ Отмена", callback_data="menu")
            ]
        ])
    )


async def delete_yes(update, context):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    con = connect()
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.execute("DELETE FROM likes WHERE user_id=? OR target_id=?", (uid, uid))
    con.execute("DELETE FROM skips WHERE user_id=? OR target_id=?", (uid, uid))
    con.execute("DELETE FROM blocks WHERE user_id=? OR target_id=?", (uid, uid))
    con.commit()
    con.close()

    await q.edit_message_text(
        "🗑 Анкета удалена.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Создать заново", callback_data="recreate")]
        ])
    )


async def recreate(update, context):
    q = update.callback_query
    await q.answer()

    await q.message.reply_text(
        "Давай создадим новую анкету.\n\nКак тебя зовут?"
    )
    return NAME


# =========================
# РЕДАКТИРОВАНИЕ
# =========================
async def edit_profile(update, context):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "✏️ Для полной замены анкеты сначала удали старую, "
        "затем создай новую.\n\n"
        "Это сделано, чтобы не потерять данные случайно.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Удалить анкету", callback_data="delete_confirm")],
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
        ])
    )


# =========================
# ПОМОЩЬ / НАСТРОЙКИ
# =========================
async def settings(update, context):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "⚙️ <b>Настройки</b>\n\n"
        "• Возраст анкеты: 18+\n"
        "• Фото можно заменить через пересоздание анкеты.\n"
        "• Заблокированные пользователи не показываются.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
        ])
    )


async def help_page(update, context):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        "❓ <b>Как пользоваться Дайв 2</b>\n\n"
        "🔎 Смотреть анкеты — поиск людей.\n"
        "❤️ Лайк — понравился человек.\n"
        "❌ Пропуск — больше не показывать анкету.\n"
        "💕 Мэтч — вы понравились друг другу.\n"
        "🚫 Блок — скрыть пользователя.\n"
        "⚠️ Жалоба — сообщить администрации.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")]
        ])
    )


# =========================
# АДМИН-ПАНЕЛЬ
# =========================
def admin_only(user_id):
    return user_id == ADMIN_ID


async def admin(update, context):
    uid = update.effective_user.id

    if not admin_only(uid):
        await update.message.reply_text("⛔ Нет доступа.")
        return

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_reports")],
        [InlineKeyboardButton("🚫 Заблокированные", callback_data="admin_banned")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast_help")]
    ]

    await update.message.reply_text(
        "🛡️ <b>АДМИН-ПАНЕЛЬ ДАЙВ 2</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_callbacks(update, context):
    q = update.callback_query
    uid = q.from_user.id

    if not admin_only(uid):
        await q.answer("⛔ Нет доступа.", show_alert=True)
        return

    await q.answer()
    data = q.data

    con = connect()

    if data == "admin_stats":
        users = con.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]
        active = con.execute(
            "SELECT COUNT(*) c FROM users WHERE is_banned=0"
        ).fetchone()["c"]
        likes = con.execute(
            "SELECT COUNT(*) c FROM likes"
        ).fetchone()["c"]
        matches_count = con.execute("""
            SELECT COUNT(*) c
            FROM likes a
            JOIN likes b
              ON a.user_id=b.target_id AND a.target_id=b.user_id
            WHERE a.user_id < a.target_id
        """).fetchone()["c"]
        reports = con.execute(
            "SELECT COUNT(*) c FROM reports WHERE status='new'"
        ).fetchone()["c"]

        text = (
            "📊 <b>Статистика</b>\n\n"
            f"👥 Всего пользователей: <b>{users}</b>\n"
            f"🟢 Активных: <b>{active}</b>\n"
            f"❤️ Лайков: <b>{likes}</b>\n"
            f"💕 Мэтчей: <b>{matches_count}</b>\n"
            f"⚠️ Новых жалоб: <b>{reports}</b>"
        )

    elif data == "admin_users":
        rows = con.execute("""
            SELECT id,name,age,city,is_banned
            FROM users
            ORDER BY created_at DESC
            LIMIT 30
        """).fetchall()

        if not rows:
            text = "👥 Пользователей нет."
        else:
            text = "👥 <b>Последние пользователи:</b>\n\n"
            for r in rows:
                status = "🚫" if r["is_banned"] else "🟢"
                text += f"{status} <code>{r['id']}</code> — {r['name']}, {r['age']} — {r['city']}\n"

    elif data == "admin_banned":
        rows = con.execute("""
            SELECT id,name,age,city
            FROM users
            WHERE is_banned=1
            ORDER BY name
            LIMIT 50
        """).fetchall()

        if not rows:
            text = "🚫 Заблокированных пользователей нет."
        else:
            text = "🚫 <b>Заблокированные:</b>\n\n"
            text += "\n".join(
                f"<code>{r['id']}</code> — {r['name']}, {r['age']} — {r['city']}"
                for r in rows
            )

    elif data == "admin_reports":
        rows = con.execute("""
            SELECT id,reporter_id,target_id,reason,status,created_at
            FROM reports
            WHERE status='new'
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()

        if not rows:
            text = "⚠️ Новых жалоб нет."
        else:
            text = "⚠️ <b>Новые жалобы:</b>\n\n"
            for r in rows:
                text += (
                    f"#{r['id']} | от <code>{r['reporter_id']}</code> "
                    f"на <code>{r['target_id']}</code>\n"
                    f"Причина: {r['reason']}\n\n"
                )

    else:
        con.close()
        await q.edit_message_text(
            "📢 Рассылка:\n\n"
            "Используй команду:\n"
            "<code>/broadcast Текст сообщения</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_back")]
            ])
        )
        return

    con.close()

    await q.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Админ-панель", callback_data="admin_back")]
        ])
    )


async def admin_back(update, context):
    q = update.callback_query
    await q.answer()

    if q.from_user.id != ADMIN_ID:
        return

    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_reports")],
        [InlineKeyboardButton("🚫 Заблокированные", callback_data="admin_banned")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast_help")]
    ]

    await q.edit_message_text(
        "🛡️ <b>АДМИН-ПАНЕЛЬ</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    if not context.args:
        await update.message.reply_text(
            "Использование:\n/broadcast Текст сообщения"
        )
        return

    text = " ".join(context.args)

    con = connect()
    users = con.execute(
        "SELECT id FROM users WHERE is_banned=0"
    ).fetchall()
    con.close()

    sent = 0
    failed = 0

    for row in users:
        try:
            await context.bot.send_message(row["id"], text)
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 Рассылка завершена.\n\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}"
    )


# =========================
# ТЕКСТОВЫЕ КОМАНДЫ
# =========================
async def menu_command(update, context):
    if await banned_guard(update):
        return
    if not get_user(update.effective_user.id):
        await update.message.reply_text("Сначала создай анкету через /start.")
        return
    await send_menu(update)


async def unknown(update, context):
    if await banned_guard(update):
        return
    await update.message.reply_text(
        "Используй /menu или кнопки меню."
    )


# =========================
# CALLBACK ROUTER
# =========================
async def callback_router(update, context):
    q = update.callback_query
    data = q.data

    if data.startswith("like:") or data.startswith("skip:") \
            or data.startswith("block:") or data.startswith("report:"):
        await profile_action(update, context)
    elif data == "menu":
        await q.answer()
        await send_menu(update)
    elif data == "browse":
        await browse(update, context)
    elif data == "profile":
        await show_profile(update, context)
    elif data == "mylikes":
        await my_likes(update, context)
    elif data == "matches":
        await matches(update, context)
    elif data == "edit":
        await edit_profile(update, context)
    elif data == "settings":
        await settings(update, context)
    elif data == "help":
        await help_page(update, context)
    elif data == "delete_confirm":
        await delete_confirm(update, context)
    elif data == "delete_yes":
        await delete_yes(update, context)
    elif data == "recreate":
        # Нельзя нормально продолжить ConversationHandler из обычного callback
        # Поэтому даём команду /start.
        await q.answer()
        await q.edit_message_text(
            "Для создания новой анкеты нажми /start."
        )
    elif data.startswith("admin_"):
        await admin_callbacks(update, context)


# =========================
# ЗАПУСК
# =========================
async def health(request):
    return web.Response(text="OK")


async def telegram_webhook(request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return web.Response(status=403, text="Forbidden")
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response(text="OK")
    except Exception:
        logger.exception("Ошибка обработки webhook")
        return web.Response(status=500, text="Webhook error")


def add_handlers(app):
    registration = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_about)],
            PHOTO: [MessageHandler(filters.PHOTO, get_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(registration)
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))


async def main():
    global application

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Добавь переменную BOT_TOKEN в Render.")

    init_db()
    application = Application.builder().token(BOT_TOKEN).build()
    add_handlers(application)

    public_url = (os.getenv("PUBLIC_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()).rstrip("/")
    if not public_url:
        raise RuntimeError("Не найден RENDER_EXTERNAL_URL. Для локального запуска задай PUBLIC_URL.")

    port = int(os.getenv("PORT", "10000"))
    webhook_path = "telegram-webhook"
    webhook_url = f"{public_url}/{webhook_path}"

    await application.initialize()
    await application.start()
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
    )

    server = web.Application()
    server.router.add_get("/", health)
    server.router.add_get("/health", health)
    server.router.add_post(f"/{webhook_path}", telegram_webhook)

    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info("Дайв 2 запущен на порту %s", port)
    logger.info("Webhook: %s", webhook_url)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await application.stop()
        await application.shutdown()


application = None

if __name__ == "__main__":
    asyncio.run(main())
