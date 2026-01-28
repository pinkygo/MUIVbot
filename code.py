import json
import os
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8427989876:AAGC5kzNUEmlZAsAgDGl8ydp4N3OnVCcs0c"

# Хранилище пользователей
users_storage = {}  # {user_id: {username, first_name, last_name, chat_id, joined_date}}
chat_users = {}  # {chat_id: [user_ids]}
chat_admins = {}  # {chat_id: [admin_user_ids]} - кэш администраторов
recent_tags = {}  # {chat_id: {user_id: timestamp}} - для предотвращения дублирования

# Ссылки на сайты
SCHEDULE_URL = "https://www.muiv.ru/studentu/spo/raspisanie/"
PERSONAL_ACCOUNT_URL = "https://e.muiv.ru/login/index.php"
EDUCATION_PROGRAMS_URL = "https://www.muiv.ru/sveden/education/oop/"

# Файл для сохранения данных
DATA_FILE = "users_data.json"


# Функции для сохранения и загрузки данных
def save_users_to_file():
    """Сохраняет пользователей в файл JSON"""
    try:
        data_to_save = {
            'users_storage': users_storage,
            'chat_users': chat_users
        }

        # Преобразуем datetime объекты в строки
        for user_id, user_data in data_to_save['users_storage'].items():
            for key, value in user_data.items():
                if isinstance(value, datetime):
                    data_to_save['users_storage'][user_id][key] = value.isoformat()

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Сохранено {len(users_storage)} пользователей в файл")
    except Exception as e:
        logger.error(f"❌ Ошибка при сохранении данных: {e}")


def load_users_from_file():
    """Загружает пользователей из файла JSON"""
    global users_storage, chat_users

    if not os.path.exists(DATA_FILE):
        logger.info("📁 Файл данных не найден, начинаем с нуля")
        return

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)

        # Восстанавливаем данные
        users_storage = loaded_data.get('users_storage', {})
        chat_users = loaded_data.get('chat_users', {})

        # Преобразуем ключи из строк обратно в int
        users_storage = {int(k): v for k, v in users_storage.items()}
        chat_users = {int(k): v for k, v in chat_users.items()}

        # Преобразуем строки даты обратно в объекты datetime
        for user_id, user_data in users_storage.items():
            for key in ['joined_date', 'last_active']:
                if key in user_data and isinstance(user_data[key], str):
                    try:
                        users_storage[user_id][key] = datetime.fromisoformat(user_data[key])
                    except:
                        pass

        logger.info(f"📂 Загружено {len(users_storage)} пользователей из файла")
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке данных: {e}")
        users_storage = {}
        chat_users = {}


# Создаем клавиатуру с кнопками
def get_main_keyboard(chat_id=None, user_id=None):
    """Создает основную клавиатуру с кнопками в зависимости от прав"""
    keyboard = []

    if chat_id:  # Если в группе
        # Проверяем, является ли пользователь администратором
        is_admin = False
        if chat_id and user_id:
            is_admin = user_id in chat_admins.get(chat_id, [])

        if is_admin:
            keyboard = [
                [KeyboardButton("📋 Список пользователей"), KeyboardButton("🔔 Тегнуть всех")],
                [KeyboardButton("👑 Админ-панель"), KeyboardButton("📅 Расписание")],
                [KeyboardButton("👤 Личный кабинет"), KeyboardButton("📚 Рабочие программы")],
                [KeyboardButton("❓ Помощь")]
            ]
        else:
            # Обычные пользователи
            keyboard = [
                [KeyboardButton("➕ Добавить себя"), KeyboardButton("📋 Список пользователей")],
                [KeyboardButton("🔔 Тегнуть всех"), KeyboardButton("📅 Расписание")],
                [KeyboardButton("👤 Личный кабинет"), KeyboardButton("📚 Рабочие программы")],
                [KeyboardButton("❓ Помощь")]
            ]
    else:  # Если в личных сообщениях
        keyboard = [
            [KeyboardButton("📋 Список пользователей"), KeyboardButton("🔔 Тегнуть всех")],
            [KeyboardButton("➕ Добавить себя"), KeyboardButton("📅 Расписание")],
            [KeyboardButton("👤 Личный кабинет"), KeyboardButton("📚 Рабочие программы")],
            [KeyboardButton("❓ Помощь")]
        ]

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def get_admin_keyboard():
    """Создает клавиатуру для админов"""
    keyboard = [
        [KeyboardButton("🔨 Тегнуть пользователя"), KeyboardButton("📊 Статистика")],
        [KeyboardButton("👥 Список админов"), KeyboardButton("⚙️ Настройки")],
        [KeyboardButton("📅 Расписание"), KeyboardButton("👤 Личный кабинет")],
        [KeyboardButton("📚 Рабочие программы"), KeyboardButton("◀️ Назад в меню")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_tag_keyboard(chat_id):
    """Создает клавиатуру для быстрого тегирования (только для админов)"""
    keyboard = []
    users_in_chat = []

    # Получаем пользователей этого чата
    for user_id in chat_users.get(chat_id, []):
        if user_id in users_storage:
            user_data = users_storage[user_id]
            if user_data.get('username'):
                users_in_chat.append((user_id, user_data))

    if not users_in_chat:
        return None

    # Сортируем по username и берем последних 12
    users_in_chat.sort(key=lambda x: x[1].get('username', '').lower())
    recent_users = users_in_chat[-12:] if len(users_in_chat) > 12 else users_in_chat

    for i in range(0, len(recent_users), 3):
        row = []
        for j in range(3):
            if i + j < len(recent_users):
                user_id, user_data = recent_users[i + j]
                username = user_data.get('username')
                if username:
                    row.append(KeyboardButton(f"@{username}"))
        if row:
            keyboard.append(row)

    keyboard.append([KeyboardButton("◀️ Назад")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def should_allow_tag(chat_id, user_id, username):
    """Проверяет, можно ли отправить тег (предотвращение дублирования)"""
    current_time = datetime.now().timestamp()

    # Инициализируем хранилище для чата, если нужно
    if chat_id not in recent_tags:
        recent_tags[chat_id] = {}

    # Ищем ID пользователя по username
    target_user_id = None
    for uid, data in users_storage.items():
        if data.get('username', '').lower() == username.lower():
            target_user_id = uid
            break

    if not target_user_id:
        return True  # Пользователь не найден, но пусть бот отправит ошибку

    # Проверяем, не тегали ли этого пользователя недавно
    tag_key = f"{user_id}_{target_user_id}"

    if tag_key in recent_tags[chat_id]:
        last_tag_time = recent_tags[chat_id][tag_key]
        # Если прошло меньше 30 секунд - блокируем
        if current_time - last_tag_time < 30:
            return False

    # Обновляем время последнего тега
    recent_tags[chat_id][tag_key] = current_time

    # Очищаем старые записи (старше 60 секунд)
    to_delete = []
    for key, timestamp in recent_tags[chat_id].items():
        if current_time - timestamp > 60:
            to_delete.append(key)

    for key in to_delete:
        del recent_tags[chat_id][key]

    return True


async def check_admin(update: Update, context: CallbackContext, user_id=None):
    """Проверяет, является ли пользователь администратором"""
    chat = update.effective_chat
    user = update.effective_user if not user_id else None

    # Если это личные сообщения, считаем администратором
    if chat.type == "private":
        return True

    target_user_id = user_id if user_id else user.id

    try:
        # Получаем список администраторов чата
        admins = await chat.get_administrators()

        # Кэшируем результат
        if chat.id not in chat_admins:
            chat_admins[chat.id] = []

        chat_admins[chat.id] = [admin.user.id for admin in admins]

        # Проверяем, есть ли пользователь среди администраторов
        is_admin = target_user_id in chat_admins[chat.id]

        # Также проверяем, является ли пользователь создателем чата
        if not is_admin:
            for admin in admins:
                if admin.user.id == target_user_id and admin.status == 'creator':
                    is_admin = True
                    break

        return is_admin
    except Exception as e:
        logger.error(f"Ошибка при проверке прав администратора: {e}")
        return False


async def require_admin(func):
    """Декоратор для проверки прав администратора (только для тегирования конкретных пользователей)"""

    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        # Если это личные сообщения - разрешаем
        if update.effective_chat.type == "private":
            return await func(update, context, *args, **kwargs)

        # Проверяем права администратора
        if not await check_admin(update, context):
            await update.message.reply_text(
                "❌ У вас недостаточно прав!\n"
                "Только администраторы могут тегнуть конкретных пользователей."
            )
            return

        # Если администратор - выполняем функцию
        return await func(update, context, *args, **kwargs)

    return wrapper


# Автоматическая регистрация пользователя при любом сообщении
async def auto_register_user(update: Update, context: CallbackContext) -> None:
    """Автоматически регистрирует пользователя при любом сообщении"""
    user = update.effective_user
    chat = update.effective_chat

    user_was_new = False

    if user.id not in users_storage:
        # Регистрируем нового пользователя
        users_storage[user.id] = {
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'chat_id': chat.id,
            'joined_date': datetime.now(),
            'last_active': datetime.now(),
            'is_admin': False
        }
        user_was_new = True

        # Проверяем, является ли администратором
        if chat.type != "private":
            users_storage[user.id]['is_admin'] = await check_admin(update, context)

        # Добавляем пользователя в список участников чата
        if chat.id not in chat_users:
            chat_users[chat.id] = []

        if user.id not in chat_users[chat.id]:
            chat_users[chat.id].append(user.id)

        logger.info(f"Новый пользователь зарегистрирован: @{user.username}")

        # Сохраняем в файл при добавлении нового пользователя
        save_users_to_file()
    else:
        # Обновляем информацию о существующем пользователе
        users_storage[user.id]['last_active'] = datetime.now()

        # Обновляем username если изменился
        if users_storage[user.id]['username'] != user.username:
            users_storage[user.id]['username'] = user.username
            logger.info(f"Обновлен username для пользователя {user.id}: @{user.username}")

        # Обновляем chat_id если изменился
        old_chat_id = users_storage[user.id]['chat_id']
        if old_chat_id != chat.id:
            # Удаляем из старого чата
            if old_chat_id in chat_users and user.id in chat_users[old_chat_id]:
                chat_users[old_chat_id].remove(user.id)

            users_storage[user.id]['chat_id'] = chat.id

            # Добавляем в новый чат
            if chat.id not in chat_users:
                chat_users[chat.id] = []
            if user.id not in chat_users[chat.id]:
                chat_users[chat.id].append(user.id)

        # Обновляем статус администратора
        if chat.type != "private":
            users_storage[user.id]['is_admin'] = await check_admin(update, context)

        # Добавляем в список участников чата
        if chat.id not in chat_users:
            chat_users[chat.id] = []
        if user.id not in chat_users[chat.id]:
            chat_users[chat.id].append(user.id)

        # Сохраняем изменения
        save_users_to_file()


# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    chat = update.effective_chat

    # Регистрируем пользователя
    users_storage[user.id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'chat_id': chat.id,
        'joined_date': datetime.now(),
        'last_active': datetime.now(),
        'is_admin': False
    }

    # Проверяем права администратора
    if chat.type != "private":
        users_storage[user.id]['is_admin'] = await check_admin(update, context)

    # Добавляем в список участников чата
    if chat.id not in chat_users:
        chat_users[chat.id] = []

    if user.id not in chat_users[chat.id]:
        chat_users[chat.id].append(user.id)

    # Сохраняем данные
    save_users_to_file()

    # Определяем приветствие в зависимости от прав
    if chat.type == "private":
        welcome_text = (
            f"👋 Привет, {user.first_name}!\n\n"
            "🤖 Я бот для тегирования пользователей по юзернейму\n\n"
            "📌 *В группах только администраторы могут тегнуть конкретных пользователей*\n"
            "📌 *Все пользователи могут тегнуть всех в чате*\n\n"
            "🎓 *Полезные ссылки (доступны всем):*\n"
            "• 📅 Расписание занятий\n"
            "• 👤 Личный кабинет МУИВ\n"
            "• 📚 Рабочие программы дисциплин\n\n"
            "Используй кнопки ниже или команды."
        )
    else:
        is_admin = users_storage[user.id]['is_admin']
        admin_status = "👑 Вы администратор" if is_admin else "👤 Вы обычный пользователь"

        welcome_text = (
            f"👋 Привет, {user.first_name}!\n\n"
            "🤖 Я бот-помощник для сотрудников МУИВ. Мои возможности будут пополняться\n\n"
            f"{admin_status}\n"
            "🎓 *Полезные ссылки:*\n"
            "• 📅 Расписание занятий\n"
            "• 👤 Личный кабинет МУИВ\n"
            "• 📚 Рабочие программы дисциплин\n\n"
        )

    await update.message.reply_text(
        welcome_text,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard(chat.id, user.id)
    )


# Обработка текстовых сообщений (кнопок)
async def handle_message(update: Update, context: CallbackContext) -> None:
    """Обработка текстовых сообщений и нажатий на кнопки"""
    user = update.effective_user
    chat = update.effective_chat
    text = update.message.text

    # Сначала автоматически регистрируем пользователя
    await auto_register_user(update, context)

    # Обработка кнопок
    if text == "📋 Список пользователей":
        await list_users_button(update, context)

    elif text == "🔔 Тегнуть всех":
        await tag_all_button(update, context)

    elif text == "➕ Добавить себя":
        await addme_button(update, context)

    elif text == "❓ Помощь":
        await help_button(update, context)

    elif text == "📅 Расписание":
        await schedule_button(update, context)

    elif text == "👤 Личный кабинет":
        await personal_account_button(update, context)

    elif text == "📚 Рабочие программы":
        await education_programs_button(update, context)

    elif text == "👑 Админ-панель":
        await admin_panel_button(update, context)

    elif text == "🔨 Тегнуть пользователя":
        await tag_user_prompt(update, context)

    elif text == "📊 Статистика":
        await stats_button(update, context)

    elif text == "👥 Список админов":
        await list_admins_button(update, context)

    elif text == "⚙️ Настройки":
        await settings_button(update, context)

    elif text == "◀️ Назад в меню":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard(chat.id, user.id)
        )

    elif text == "◀️ Назад":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard(chat.id, user.id)
        )

    elif text.startswith("@"):
        # Если нажали на кнопку с @username (только для админов)
        username = text[1:]  # Убираем @
        await tag_user_by_button(update, context, username)

    elif text.startswith("/tag "):
        # Обработка команды тега через текст
        parts = text.split()
        if len(parts) > 1:
            username = parts[1].lstrip('@')
            await tag_command_internal(update, context, username, ' '.join(parts[2:]) if len(parts) > 2 else None)

    elif text.startswith("/tagall"):
        # Обработка команды тега всех
        await tagall_command(update, context)

    else:
        # Проверяем, содержит ли сообщение упоминания пользователей
        if "@" in text:
            # Проверяем, упоминает ли пользователь кого-то вручную
            words = text.split()
            for word in words:
                if word.startswith("@"):
                    username = word[1:]
                    logger.info(f"Пользователь {user.username} упомянул @{username} вручную")

        # Обычное сообщение
        if chat.type == "private":
            await update.message.reply_text(
                "Используй кнопки ниже или напиши:\n"
                "/tag @username - чтобы тегнуть пользователя (только админы)\n"
                "/tagall - чтобы тегнуть всех",
                reply_markup=get_main_keyboard(chat.id, user.id)
            )


# Кнопка расписания
async def schedule_button(update: Update, context: CallbackContext) -> None:
    """Отправляет ссылку на расписание (доступно всем)"""
    # Создаем inline кнопку под сообщением
    keyboard = [[InlineKeyboardButton("📅 Открыть расписание", url=SCHEDULE_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📅 *Расписание занятий*\n\n"
        "Ссылка на официальное расписание МУИВ:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


# Кнопка личного кабинета
async def personal_account_button(update: Update, context: CallbackContext) -> None:
    """Отправляет ссылку на личный кабинет (доступно всем)"""
    # Создаем inline кнопку под сообщением
    keyboard = [[InlineKeyboardButton("👤 Открыть личный кабинет", url=PERSONAL_ACCOUNT_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👤 *Личный кабинет МУИВ*\n\n"
        "Ссылка для входа в личный кабинет:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


# Кнопка рабочих программ
async def education_programs_button(update: Update, context: CallbackContext) -> None:
    """Отправляет ссылку на рабочие программы дисциплин (доступно всем)"""
    # Создаем inline кнопку под сообщением
    keyboard = [[InlineKeyboardButton("📚 Открыть рабочие программы", url=EDUCATION_PROGRAMS_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📚 *Рабочие программы дисциплин*\n\n"
        "Ссылка на рабочие программы образовательных программ МУИВ:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


# Админ-панель (только для админов)
@require_admin
async def admin_panel_button(update: Update, context: CallbackContext) -> None:
    """Показать админ-панель"""
    await update.message.reply_text(
        "👑 *Админ-панель*\n\n"
        "Доступные функции:\n"
        "• Тегнуть конкретного пользователя (только админы)\n"
        "• Просмотр статистики\n"
        "• Список администраторов\n"
        "• Полезные ссылки для студентов\n\n"
        "Выберите действие:",
        parse_mode='Markdown',
        reply_markup=get_admin_keyboard()
    )


# Тегнуть пользователя (только для админов)
@require_admin
async def tag_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /tag (только для админов)"""
    if not context.args:
        await update.message.reply_text(
            "❌ Укажите username пользователя!\n"
            "Пример: `/tag username`\n"
            "Или: `/tag @username сообщение`",
            parse_mode='Markdown'
        )
        return

    username = context.args[0].lstrip('@').lower()
    message = ' '.join(context.args[1:]) if len(context.args) > 1 else None
    await tag_command_internal(update, context, username, message)


async def tag_command_internal(update: Update, context: CallbackContext, username: str, message: str = None):
    """Внутренняя функция для тегирования (только для админов)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Проверяем, не дублируется ли тег
    if not should_allow_tag(chat_id, user_id, username):
        await update.message.reply_text(
            "⏳ Вы недавно уже тегнули этого пользователя.\n"
            "Пожалуйста, подождите немного перед следующим тегом."
        )
        return

    # Ищем пользователя по username (без учета регистра)
    found_user = None
    for uid, user_data in users_storage.items():
        if user_data.get('username', '').lower() == username:
            found_user = user_data
            break

    if found_user:
        if message:
            response = f"🔔 @{found_user['username']} {message}"
        else:
            response = f"🔔 @{found_user['username']}"

        await update.message.reply_text(response)
    else:
        await update.message.reply_text(
            f"❌ Пользователь @{username} не найден.\n"
            "Он должен написать хотя бы одно сообщение в чат с ботом."
        )


@require_admin
async def tag_user_by_button(update: Update, context: CallbackContext, username: str):
    """Тегнуть пользователя при нажатии на кнопку (только админы)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Проверяем, не дублируется ли тег
    if not should_allow_tag(chat_id, user_id, username):
        await update.message.reply_text(
            "⏳ Вы недавно уже тегнули этого пользователя.\n"
            "Пожалуйста, подождите немного перед следующим тегом."
        )
        return

    found_user = None
    for uid, user_data in users_storage.items():
        if user_data.get('username', '').lower() == username.lower():
            found_user = user_data
            break

    if found_user:
        await update.message.reply_text(f"🔔 @{found_user['username']}")
    else:
        await update.message.reply_text(f"❌ @{username} не найден")


@require_admin
async def tag_user_prompt(update: Update, context: CallbackContext):
    """Запрос username для тегирования (только для админов)"""
    await update.message.reply_text(
        "Введите username пользователя для тега (с @ или без):\n"
        "Пример: `@username` или `username`\n\n"
        "*Только администраторы могут тегнуть конкретных пользователей*",
        parse_mode='Markdown',
        reply_markup=get_tag_keyboard(update.effective_chat.id)
    )


# Тегнуть всех (доступно всем пользователям)
async def tagall_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /tagall (доступно всем)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Получаем пользователей этого чата
    users_in_chat = []
    for uid in chat_users.get(chat_id, []):
        if uid in users_storage:
            user_data = users_storage[uid]
            if user_data.get('username'):
                users_in_chat.append(user_data)

    if not users_in_chat:
        await update.message.reply_text(
            "📭 Нет пользователей для тегирования в этом чате."
        )
        return

    # Проверяем, не использовали ли команду недавно
    current_time = datetime.now().timestamp()
    tagall_key = f"tagall_{user_id}"

    if chat_id in recent_tags and tagall_key in recent_tags[chat_id]:
        last_tagall_time = recent_tags[chat_id][tagall_key]
        if current_time - last_tagall_time < 60:  # 1 минута
            await update.message.reply_text(
                "⏳ Команда /tagall была использована недавно.\n"
                "Пожалуйста, подождите минуту перед следующим использованием."
            )
            return

    # Обновляем время использования команды
    if chat_id not in recent_tags:
        recent_tags[chat_id] = {}
    recent_tags[chat_id][tagall_key] = current_time

    tags = []
    for user_data in users_in_chat:
        tags.append(f"@{user_data['username']}")

    # Добавляем сообщение о том, кто тегнул
    user = update.effective_user
    mention = f"@{user.username}" if user.username else user.first_name
    response = f"🔔 {mention} тегнул(а) всех:\n" + " ".join(tags)

    await update.message.reply_text(response)


async def tag_all_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Тегнуть всех (доступно всем)"""
    await tagall_command(update, context)


# Список пользователей (доступен всем)
async def list_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /list (доступно всем)"""
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Получаем пользователей этого чата
    users_in_chat = []
    for user_id in chat_users.get(chat_id, []):
        if user_id in users_storage:
            user_data = users_storage[user_id]
            if user_data.get('username'):
                users_in_chat.append(user_data)

    if not users_in_chat:
        await update.message.reply_text(
            "📭 В этом чате еще нет зарегистрированных пользователей.\n"
            "Нажмите '➕ Добавить себя' или просто напишите любое сообщение."
        )
        return

    users_list = "📋 *Пользователи в этом чате:*\n\n"
    for i, user_data in enumerate(sorted(users_in_chat, key=lambda x: x.get('username', '').lower()), 1):
        name = user_data.get('first_name', '')
        if user_data.get('last_name'):
            name += f" {user_data['last_name']}"

        username = user_data.get('username', 'без username')
        admin_icon = " 👑" if user_data.get('is_admin') else ""
        users_list += f"{i}. @{username} - {name}{admin_icon}\n"

    users_list += f"\nВсего: {len(users_in_chat)} пользователей"


    # Показываем клавиатуру для тегирования только админам
    if await check_admin(update, context):
        tag_keyboard = get_tag_keyboard(chat_id)
        if tag_keyboard:
            await update.message.reply_text(
                users_list,
                parse_mode='Markdown',
                reply_markup=tag_keyboard
            )
        else:
            await update.message.reply_text(
                users_list,
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            users_list,
            parse_mode='Markdown'
        )


async def list_users_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Список пользователей"""
    await list_command(update, context)


# Добавить себя (доступно всем)
async def addme_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /addme (доступно всем)"""
    user = update.effective_user
    chat = update.effective_chat

    if not user.username:
        await update.message.reply_text(
            "❌ У вас не установлен username в Telegram!\n"
            "Пожалуйста, установите username в настройках Telegram:\n"
            "Настройки → Имя пользователя (Username)\n\n"
            "После установки username нажмите кнопку '➕ Добавить себя' снова.",
            parse_mode='Markdown'
        )
        return

    # Добавляем/обновляем пользователя
    users_storage[user.id] = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'chat_id': chat.id,
        'joined_date': datetime.now(),
        'last_active': datetime.now(),
        'is_admin': False
    }

    # Проверяем права администратора
    if chat.type != "private":
        users_storage[user.id]['is_admin'] = await check_admin(update, context)

    # Добавляем в список участников чата
    if chat.id not in chat_users:
        chat_users[chat.id] = []

    if user.id not in chat_users[chat.id]:
        chat_users[chat.id].append(user.id)

    # Сохраняем данные
    save_users_to_file()

    await update.message.reply_text(
        f"✅ Отлично, {user.first_name}!\n"
        f"Вы добавлены как @{user.username}\n\n"
        "🎯 *Теперь вас могут тегнуть в этом чате!*\n"
        "📌 *Администраторы могут тегнуть вас конкретно*\n"
        "📌 *Все пользователи могут тегнуть всех*\n\n",
        parse_mode='Markdown',
        reply_markup=get_main_keyboard(chat.id, user.id)
    )


async def addme_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Добавить себя"""
    await addme_command(update, context)


# Список администраторов (только для админов)
@require_admin
async def list_admins_command(update: Update, context: CallbackContext) -> None:
    """Показать список администраторов чата"""
    chat = update.effective_chat

    try:
        # Получаем список администраторов
        admins = await chat.get_administrators()

        if not admins:
            await update.message.reply_text("В этом чате нет администраторов.")
            return

        admins_list = "👑 *Администраторы чата:*\n\n"

        for i, admin in enumerate(admins, 1):
            user = admin.user
            status_icon = "👑" if admin.status == 'creator' else "⚡"
            status_text = "Создатель" if admin.status == 'creator' else "Админ"

            if user.username:
                admins_list += f"{i}. {status_icon} @{user.username} - {user.first_name} ({status_text})\n"
            else:
                admins_list += f"{i}. {status_icon} {user.first_name} ({status_text})\n"

        await update.message.reply_text(admins_list, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Ошибка при получении списка админов: {e}")
        await update.message.reply_text("Не удалось получить список администраторов.")


async def list_admins_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Список админов"""
    await list_admins_command(update, context)


# Статистика (только для админов)
@require_admin
async def stats_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /stats (только админы)"""
    chat_id = update.effective_chat.id

    total_users = len(users_storage)
    users_with_username = sum(1 for u in users_storage.values() if u.get('username'))
    total_chats = len(chat_users)

    # Пользователи в текущем чате
    users_in_this_chat = len(chat_users.get(chat_id, []))
    admins_in_this_chat = sum(1 for uid in chat_users.get(chat_id, [])
                              if uid in users_storage and users_storage[uid].get('is_admin'))

    stats_text = (
        "📊 *Статистика бота:*\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"📝 С username: {users_with_username}\n"
        f"💬 Активных чатов: {total_chats}\n\n"

        f"*Статистика этого чата:*\n"
        f"Пользователей: {users_in_this_chat}\n"
        f"Администраторов: {admins_in_this_chat}\n"
        f"Обычных пользователей: {users_in_this_chat - admins_in_this_chat}\n\n"

        f"💾 *Данные сохранены в файле:* {DATA_FILE}"
    )

    await update.message.reply_text(stats_text, parse_mode='Markdown')


async def stats_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Статистика"""
    await stats_command(update, context)


# Настройки (только для админов)
@require_admin
async def settings_button(update: Update, context: CallbackContext) -> None:
    """Кнопка настроек (заглушка)"""
    await update.message.reply_text(
        "⚙️ *Настройки*\n\n"
        "Настройки бота будут доступны в будущих обновлениях.\n"
        "Сейчас вы можете:\n"
        "• Использовать /tag для тегирования (только админы)\n"
        "• Использовать /tagall для тега всех (все пользователи)\n"
        "• Просматривать статистику\n"
        "• Открывать полезные ссылки для студентов\n"
        "• Данные автоматически сохраняются при перезапуске",
        parse_mode='Markdown'
    )


# Остальные функции (доступны всем)
async def help_command(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help"""
    user = update.effective_user
    chat = update.effective_chat

    is_admin = await check_admin(update, context)

    if is_admin or chat.type == "private":
        help_text = (
            "📚 *Помощь по боту*\n\n"
            "*Команды для администраторов:*\n"
            "`/tag @username` - Тегнуть конкретного пользователя\n"
            "`/admins` - Список администраторов\n"
            "`/stats` - Статистика бота\n\n"

            "*Команды для всех пользователей:*\n"
            "`/tagall` - Тегнуть всех в чате\n"
            "`/start` - Начать работу\n"
            "`/addme` - Добавить себя\n"
            "`/list` - Список пользователей\n\n"

            "*Полезные ссылки для всех (кнопки):*\n"
            "📅 Расписание - расписание занятий МУИВ\n"
            "👤 Личный кабинет - вход в личный кабинет студента\n"
            "📚 Рабочие программы - рабочие программы дисциплин\n\n"

            "*Как это работает:*\n"
            "1. Бот автоматически добавляет любого, кто пишет в чат\n"
            "2. Для тегирования нужен @username в Telegram\n"
        )
    else:
        help_text = (
            "📚 *Помощь по боту*\n\n"
            "*Команды для пользователей:*\n"
            "`/tagall` - Тегнуть всех в чате\n"
            "`/start` - Начать работу\n"
            "`/addme` - Добавить себя в базу\n"
            "`/list` - Список пользователей в чате\n\n"

            "*Полезные ссылки для всех (кнопки):*\n"
            "📅 Расписание - расписание занятий МУИВ\n"
            "👤 Личный кабинет - вход в личный кабинет студента\n"
            "📚 Рабочие программы - рабочие программы дисциплин\n\n"

            "*Как это работает:*\n"
            "1. Напишите любое сообщение в чат - бот добавит вас автоматически\n"
            "2. Установите @username в настройках Telegram\n"


        )

    await update.message.reply_text(
        help_text,
        parse_mode='Markdown',
        reply_markup=get_main_keyboard(chat.id, user.id)
    )


async def help_button(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопки Помощь"""
    await help_command(update, context)


# Функция для периодического автосохранения
import threading
import time


def auto_save_thread():
    """Фоновая задача для автосохранения данных"""
    while True:
        time.sleep(300)  # Сохраняем каждые 5 минут
        save_users_to_file()


# Основная функция
def main() -> None:
    """Запуск бота"""
    # Загружаем сохраненных пользователей
    load_users_from_file()

    # Запускаем фоновый поток для автосохранения
    save_thread = threading.Thread(target=auto_save_thread, daemon=True)
    save_thread.start()

    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("tag", tag_command))
    application.add_handler(CommandHandler("tagall", tagall_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("addme", addme_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admins", list_admins_command))

    # Регистрируем обработчик текстовых сообщений
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    # Запускаем бота
    print("🤖 Бот запущен с сохранением данных!")
    print("📌 Основные функции:")
    print("1. ✅ Сохранение пользователей в файл 'users_data.json'")
    print("2. 📅 Кнопка 'Расписание' для всех пользователей")
    print("3. 👤 Кнопка 'Личный кабинет' для всех пользователей")
    print("4. 📚 Кнопка 'Рабочие программы' для всех пользователей")
    print("5. 🔔 Все пользователи могут 'Тегнуть всех'")
    print("6. 🔐 Только админы могут тегнуть конкретных пользователей")
    print(f"7. 💾 Автосохранение каждые 5 минут")

    print(f"\n📊 Загружено пользователей: {len(users_storage)}")
    print(f"📁 Файл данных: {DATA_FILE}")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()