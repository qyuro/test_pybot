import logging
import os
import sqlite3
from datetime import datetime, timedelta

from dotenv import load_dotenv
#kjhlkajhfsdglkjhafglkjh
# from pyTelegramBotAPI import TelegramBotAPI
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
(
    SELECTING_ACTION,
    ADDING_SLOT,
    SELECTING_DATE,
    SELECTING_TIME,
    CONFIRM_BOOKING,
    SELECTING_SLOT,
) = range(6)


# Инициализация базы данных
def init_database():
    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()

    # Создаем таблицы, если их нет
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_slots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time DATETIME NOT NULL,
        end_time DATETIME NOT NULL,
        is_available BOOLEAN DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        client_username TEXT,
        status TEXT DEFAULT 'pending',
        requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        responded_at DATETIME,
        FOREIGN KEY (slot_id) REFERENCES admin_slots(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin (
        id INTEGER PRIMARY KEY,
        admin_user_id INTEGER UNIQUE NOT NULL
    )
    """)

    conn.commit()
    conn.close()


# Проверка, является ли пользователь админом
async def is_admin(user_id: int) -> bool:
    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT admin_user_id FROM admin WHERE admin_user_id = ?", (user_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result is not None


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Проверяем, является ли пользователь админом
    if await is_admin(user.id):
        await show_admin_menu(update, context)
    else:
        await show_client_menu(update, context)


# Меню для админа
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Добавить свободное время", callback_data="add_slot")],
        [InlineKeyboardButton("📋 Мои слоты", callback_data="view_my_slots")],
        [
            InlineKeyboardButton(
                "⏳ Ожидающие подтверждения", callback_data="pending_approvals"
            )
        ],
        [
            InlineKeyboardButton(
                "✅ Подтвержденные встречи", callback_data="approved_appointments"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Добро пожаловать в админ-панель!\nВыберите действие:",
        reply_markup=reply_markup,
    )


# Меню для клиента
async def show_client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton(
                "📅 Посмотреть свободное время", callback_data="view_free_slots"
            )
        ],
        [InlineKeyboardButton("📋 Мои записи", callback_data="my_bookings")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Добро пожаловать!\nВыберите действие:", reply_markup=reply_markup
    )


# Обработка нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "add_slot":
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        await query.edit_message_text(
            "Введите свободное время в формате:\n"
            "ГГГГ-ММ-ДД ЧЧ:ММ - ГГГГ-ММ-ДД ЧЧ:ММ\n"
            "Например: 2024-01-20 10:00 - 2024-01-20 12:00"
        )
        context.user_data["state"] = ADDING_SLOT

    elif data == "view_free_slots":
        await show_free_slots(query, context)

    elif data.startswith("book_"):
        slot_id = int(data.split("_")[1])
        context.user_data["booking_slot"] = slot_id

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT start_time, end_time FROM admin_slots WHERE id = ?", (slot_id,)
        )
        slot = cursor.fetchone()
        conn.close()

        if slot:
            start_time = datetime.fromisoformat(slot[0])
            end_time = datetime.fromisoformat(slot[1])

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Подтвердить запись", callback_data=f"confirm_book_{slot_id}"
                    )
                ],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel_booking")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"Вы хотите записаться на:\n"
                f"С {start_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"До {end_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Подтвердите запись:",
                reply_markup=reply_markup,
            )

    elif data.startswith("confirm_book_"):
        slot_id = int(data.split("_")[2])
        client_id = query.from_user.id
        client_username = query.from_user.username

        # Создаем запись в БД
        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        # Проверяем, свободен ли еще слот
        cursor.execute("SELECT is_available FROM admin_slots WHERE id = ?", (slot_id,))
        slot = cursor.fetchone()

        if slot and slot[0] == 1:
            # Создаем заявку
            cursor.execute(
                """
                INSERT INTO appointments (slot_id, client_id, client_username, status)
                VALUES (?, ?, ?, 'pending')
            """,
                (slot_id, client_id, client_username),
            )

            # Помечаем слот как занятый (но еще не подтвержденный)
            cursor.execute(
                "UPDATE admin_slots SET is_available = 0 WHERE id = ?", (slot_id,)
            )

            conn.commit()

            # Отправляем уведомление админу
            cursor.execute("SELECT admin_user_id FROM admin")
            admin = cursor.fetchone()

            if admin:
                slot_info = cursor.execute(
                    "SELECT start_time, end_time FROM admin_slots WHERE id = ?",
                    (slot_id,),
                ).fetchone()

                start_time = datetime.fromisoformat(slot_info[0])
                end_time = datetime.fromisoformat(slot_info[1])

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "✅ Принять", callback_data=f"approve_{slot_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ Отклонить", callback_data=f"reject_{slot_id}"
                        ),
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await context.bot.send_message(
                    admin[0],
                    f"📝 Новая заявка на запись!\n\n"
                    f"Клиент: @{client_username} (ID: {client_id})\n"
                    f"Время: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Подтвердите или отклоните заявку:",
                    reply_markup=reply_markup,
                )

            await query.edit_message_text(
                "✅ Заявка отправлена администратору!\nОжидайте подтверждения."
            )
        else:
            await query.edit_message_text("❌ Извините, это время уже недоступно.")

        conn.close()

    elif data.startswith("approve_"):
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        slot_id = int(data.split("_")[1])

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        # Получаем информацию о записи
        cursor.execute(
            """
            SELECT appointments.id, appointments.client_id, admin_slots.start_time, admin_slots.end_time
            FROM appointments
            JOIN admin_slots ON appointments.slot_id = admin_slots.id
            WHERE appointments.slot_id = ? AND appointments.status = 'pending'
        """,
            (slot_id,),
        )

        appointment = cursor.fetchone()

        if appointment:
            # Обновляем статус
            cursor.execute(
                """
                UPDATE appointments
                SET status = 'approved', responded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (appointment[0],),
            )

            conn.commit()

            # Отправляем уведомление клиенту
            start_time = datetime.fromisoformat(appointment[2])
            end_time = datetime.fromisoformat(appointment[3])

            await context.bot.send_message(
                appointment[1],
                f"✅ Ваша запись подтверждена!\n\n"
                f"Время: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Ждем вас!",
            )

            await query.edit_message_text(f"✅ Запись подтверждена!\nКлиент уведомлен.")
        else:
            await query.edit_message_text("❌ Запись не найдена или уже обработана.")

        conn.close()

    elif data.startswith("reject_"):
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        slot_id = int(data.split("_")[1])

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        # Получаем информацию о записи
        cursor.execute(
            """
            SELECT appointments.id, appointments.client_id, admin_slots.start_time, admin_slots.end_time
            FROM appointments
            JOIN admin_slots ON appointments.slot_id = admin_slots.id
            WHERE appointments.slot_id = ? AND appointments.status = 'pending'
        """,
            (slot_id,),
        )

        appointment = cursor.fetchone()

        if appointment:
            # Обновляем статус
            cursor.execute(
                """
                UPDATE appointments
                SET status = 'rejected', responded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (appointment[0],),
            )

            # Возвращаем слот в доступные
            cursor.execute(
                "UPDATE admin_slots SET is_available = 1 WHERE id = ?", (slot_id,)
            )

            conn.commit()

            # Отправляем уведомление клиенту
            start_time = datetime.fromisoformat(appointment[2])
            end_time = datetime.fromisoformat(appointment[3])

            await context.bot.send_message(
                appointment[1],
                f"❌ К сожалению, ваша запись на\n"
                f"{start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"была отклонена администратором.",
            )

            await query.edit_message_text(f"❌ Запись отклонена.\nКлиент уведомлен.")
        else:
            await query.edit_message_text("❌ Запись не найдена или уже обработана.")

        conn.close()

    elif data == "view_my_slots":
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, start_time, end_time, is_available
            FROM admin_slots
            WHERE start_time > datetime('now')
            ORDER BY start_time
        """)

        slots = cursor.fetchall()
        conn.close()

        if not slots:
            await query.edit_message_text("📅 У вас нет запланированных слотов.")
            return

        text = "📅 Ваши слоты:\n\n"
        for slot in slots:
            start_time = datetime.fromisoformat(slot[1])
            end_time = datetime.fromisoformat(slot[2])
            status = "✅ Свободен" if slot[3] else "⏳ Занят (ожидает или подтвержден)"
            text += f"ID: {slot[0]}\n{start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n{status}\n\n"

        await query.edit_message_text(text)

    elif data == "pending_approvals":
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT appointments.id, appointments.client_username,
                   admin_slots.start_time, admin_slots.end_time, admin_slots.id
            FROM appointments
            JOIN admin_slots ON appointments.slot_id = admin_slots.id
            WHERE appointments.status = 'pending'
            ORDER BY appointments.requested_at
        """)

        pending = cursor.fetchall()
        conn.close()

        if not pending:
            await query.edit_message_text("✅ Нет ожидающих подтверждения записей.")
            return

        for appointment in pending:
            start_time = datetime.fromisoformat(appointment[2])
            end_time = datetime.fromisoformat(appointment[3])

            keyboard = [
                [
                    InlineKeyboardButton(
                        "✅ Принять", callback_data=f"approve_{appointment[4]}"
                    ),
                    InlineKeyboardButton(
                        "❌ Отклонить", callback_data=f"reject_{appointment[4]}"
                    ),
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.message.reply_text(
                f"📝 Заявка #{appointment[0]}\n"
                f"Клиент: @{appointment[1]}\n"
                f"Время: {start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}",
                reply_markup=reply_markup,
            )

    elif data == "approved_appointments":
        if not await is_admin(user_id):
            await query.edit_message_text("❌ У вас нет прав администратора.")
            return

        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        cursor.execute("""
            SELECT appointments.client_username, admin_slots.start_time, admin_slots.end_time
            FROM appointments
            JOIN admin_slots ON appointments.slot_id = admin_slots.id
            WHERE appointments.status = 'approved' AND admin_slots.start_time > datetime('now')
            ORDER BY admin_slots.start_time
        """)

        approved = cursor.fetchall()
        conn.close()

        if not approved:
            await query.edit_message_text("✅ Нет предстоящих подтвержденных встреч.")
            return

        text = "✅ Подтвержденные встречи:\n\n"
        for app in approved:
            start_time = datetime.fromisoformat(app[1])
            end_time = datetime.fromisoformat(app[2])
            text += f"Клиент: @{app[0]}\n{start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n\n"

        await query.edit_message_text(text)

    elif data == "my_bookings":
        conn = sqlite3.connect("appointments.db")
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT admin_slots.start_time, admin_slots.end_time, appointments.status
            FROM appointments
            JOIN admin_slots ON appointments.slot_id = admin_slots.id
            WHERE appointments.client_id = ? AND admin_slots.start_time > datetime('now')
            ORDER BY admin_slots.start_time
        """,
            (user_id,),
        )

        bookings = cursor.fetchall()
        conn.close()

        if not bookings:
            await query.edit_message_text("📋 У вас нет активных записей.")
            return

        text = "📋 Ваши записи:\n\n"
        for booking in bookings:
            start_time = datetime.fromisoformat(booking[0])
            end_time = datetime.fromisoformat(booking[1])
            status_map = {
                "pending": "⏳ Ожидает подтверждения",
                "approved": "✅ Подтверждено",
                "rejected": "❌ Отклонено",
            }
            text += f"{start_time.strftime('%d.%m.%Y %H:%M')} - {end_time.strftime('%d.%m.%Y %H:%M')}\n{status_map[booking[2]]}\n\n"

        await query.edit_message_text(text)

    elif data == "cancel_booking":
        await query.edit_message_text("❌ Запись отменена.")


# Показать свободные слоты клиенту
async def show_free_slots(query, context):
    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, start_time, end_time
        FROM admin_slots
        WHERE is_available = 1 AND start_time > datetime('now')
        ORDER BY start_time
        LIMIT 10
    """)

    slots = cursor.fetchall()
    conn.close()

    if not slots:
        await query.edit_message_text(
            "😔 К сожалению, сейчас нет свободного времени для записи.\n"
            "Попробуйте позже."
        )
        return

    keyboard = []
    for slot in slots:
        start_time = datetime.fromisoformat(slot[1])
        end_time = datetime.fromisoformat(slot[2])
        button_text = (
            f"{start_time.strftime('%d.%m %H:%M')} - {end_time.strftime('%H:%M')}"
        )
        keyboard.append(
            [InlineKeyboardButton(button_text, callback_data=f"book_{slot[0]}")]
        )

    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_booking")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📅 Доступное время для записи:\nВыберите удобный слот:",
        reply_markup=reply_markup,
    )


# Обработка текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.user_data.get("state") == ADDING_SLOT:
        if not await is_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав администратора.")
            return

        # Парсим введенное время
        text = update.message.text
        try:
            parts = text.split("-")
            if len(parts) == 2:
                start_str = parts[0].strip()
                end_str = parts[1].strip()

                start_time = datetime.fromisoformat(start_str)
                end_time = datetime.fromisoformat(end_str)

                if start_time < datetime.now():
                    await update.message.reply_text(
                        "❌ Нельзя добавить время в прошлом."
                    )
                    return

                if end_time <= start_time:
                    await update.message.reply_text(
                        "❌ Время окончания должно быть позже времени начала."
                    )
                    return

                # Сохраняем в БД
                conn = sqlite3.connect("appointments.db")
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO admin_slots (start_time, end_time) VALUES (?, ?)",
                    (start_time.isoformat(), end_time.isoformat()),
                )
                conn.commit()
                conn.close()

                await update.message.reply_text(
                    f"✅ Слот успешно добавлен!\n"
                    f"С {start_time.strftime('%d.%m.%Y %H:%M')} до {end_time.strftime('%d.%m.%Y %H:%M')}"
                )

                # Показываем админ-меню
                await show_admin_menu(update, context)
                context.user_data["state"] = None
            else:
                await update.message.reply_text(
                    "❌ Неправильный формат. Используйте: ГГГГ-ММ-ДД ЧЧ:ММ - ГГГГ-ММ-ДД ЧЧ:ММ"
                )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Ошибка парсинга даты: {str(e)}\n"
                "Используйте формат: ГГГГ-ММ-ДД ЧЧ:ММ - ГГГГ-ММ-ДД ЧЧ:ММ"
            )


# Команда для установки админа (только первый запуск)
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = sqlite3.connect("appointments.db")
    cursor = conn.cursor()

    # Проверяем, есть ли уже админ
    cursor.execute("SELECT admin_user_id FROM admin")
    existing_admin = cursor.fetchone()

    if existing_admin:
        await update.message.reply_text("❌ Админ уже установлен.")
    else:
        cursor.execute("INSERT INTO admin (admin_user_id) VALUES (?)", (user_id,))
        conn.commit()
        await update.message.reply_text(
            "✅ Вы установлены как администратор!\n"
            "Теперь вы можете добавлять свободное время и управлять записями."
        )

    conn.close()


def main():
    # Инициализируем базу данных
    init_database()

    # Токен бота (получите у @BotFather)
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

    # Создаем приложение
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("setadmin", set_admin))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Запускаем бота
    print("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
