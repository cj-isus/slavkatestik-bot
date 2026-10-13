"""Telegram-бот с меню реферальных ссылок на работу.

Структура меню:
    Главное меню (категории)
        └── Категория (список предложений)
                └── Предложение -> кнопка с реферальной ссылкой

Контент хранится в content.json и перечитывается командой /reload
(без перезапуска бота).
"""

import asyncio
import json
import logging
import os
import signal
import threading
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import NetworkError, RetryAfter, TimedOut, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, OWNER_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CONTENT_PATH = Path(__file__).with_name("content.json")
GUIDES_PATH = Path(__file__).with_name("guides.json")
MEDIA_DIR = Path(__file__).with_name("media")

# Хранилище контента, которое можно перезагружать на лету.
CONTENT: dict = {}
# Пошаговые инструкции: ключ — название сервиса (title в content.json).
GUIDES: dict = {}


def load_content() -> dict:
    """Читает content.json и возвращает словарь с контентом."""
    with CONTENT_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_guides() -> dict:
    """Читает guides.json (пошаговые инструкции по сервисам)."""
    if not GUIDES_PATH.exists():
        return {}
    with GUIDES_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def get_categories() -> list:
    return CONTENT.get("categories", [])


def get_category(index: int) -> dict | None:
    categories = get_categories()
    if 0 <= index < len(categories):
        return categories[index]
    return None


# ---------------------------------------------------------------- клавиатуры

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Кнопки главного меню: по кнопке на каждую категорию."""
    buttons = []
    for index, category in enumerate(get_categories()):
        title = f"{category.get('emoji', '')} {category.get('title', 'Без названия')}"
        buttons.append(
            [InlineKeyboardButton(title, callback_data=f"cat:{index}")]
        )
    buttons.append([InlineKeyboardButton("ℹ️ Помощь", callback_data="help")])
    return InlineKeyboardMarkup(buttons)


def category_keyboard(index: int) -> InlineKeyboardMarkup:
    """Кнопки-список сервисов внутри категории + назад/в начало."""
    category = get_category(index) or {}
    buttons = []
    for item_index, item in enumerate(category.get("items", [])):
        title = item.get("title", "Ссылка")
        buttons.append(
            [InlineKeyboardButton(f"📖 {title}", callback_data=f"item:{index}:{item_index}")]
        )
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="home")])
    return InlineKeyboardMarkup(buttons)


def item_text(category: dict, item: dict) -> str:
    """Текст экрана сервиса: описание + пошаговая инструкция со ссылками."""
    title = item.get("title", "Сервис")
    header = (
        f"{category.get('emoji', '')} <b>{title}</b>\n"
        f"{item.get('description', '')}"
    )
    guide = GUIDES.get(title)
    steps = guide.get("steps", []) if isinstance(guide, dict) else (guide or [])
    if steps:
        numbered = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
        header += f"\n\n<b>Как начать:</b>\n{numbered}"
    else:
        header += "\n\nИнструкция появится позже."
    return header


def item_keyboard(category_index: int, item_index: int, url: str) -> InlineKeyboardMarkup:
    """Кнопки экрана сервиса: открыть ссылку + назад в категорию."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Открыть сервис ↗", url=url)],
            [InlineKeyboardButton("◀️ Назад", callback_data=f"cat:{category_index}")],
        ]
    )


# ------------------------------------------------------------------ хендлеры

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветствие и главное меню."""
    text = CONTENT.get("welcome_text", "Выберите раздел:")
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=main_menu_keyboard()
        )
    elif update.message:
        await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(CONTENT.get("help_text", "Нет описания."))


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Перечитывает content.json (только для владельца)."""
    user_id = update.effective_user.id
    if OWNER_ID and user_id != OWNER_ID:
        await update.message.reply_text("Команда доступна только владельцу бота.")
        return
    try:
        CONTENT.update(load_content())
    except (json.JSONDecodeError, OSError) as exc:
        await update.message.reply_text(f"Ошибка чтения content.json: {exc}")
        return
    try:
        GUIDES.clear()
        GUIDES.update(load_guides())
    except (json.JSONDecodeError, OSError) as exc:
        await update.message.reply_text(f"Ошибка чтения guides.json: {exc}")
        return
    await update.message.reply_text(
        f"Контент перезагружен. Разделов: {len(get_categories())}, "
        f"инструкций: {len(GUIDES)}."
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка нажатий inline-кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "home":
        await cmd_start(update, context)
        return

    if data == "help":
        await query.edit_message_text(
            CONTENT.get("help_text", "Нет описания."),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Назад", callback_data="home")]]
            ),
        )
        return

    if data.startswith("item:"):
        try:
            cat_index, item_index = (int(part) for part in data.split(":", 2)[1:])
        except ValueError:
            return
        category = get_category(cat_index)
        if not category:
            return
        items = category.get("items", [])
        if not 0 <= item_index < len(items):
            return
        item = items[item_index]
        text = item_text(category, item)
        keyboard = item_keyboard(cat_index, item_index, item.get("url", ""))

        # Скриншот инструкции: положи файл media/<название сервиса>.jpg|png
        photo_path = MEDIA_DIR / f"{item.get('title', '')}.jpg"
        if not photo_path.exists():
            photo_path = MEDIA_DIR / f"{item.get('title', '')}.png"
        if photo_path.exists():
            with photo_path.open("rb") as fh:
                await query.message.reply_photo(photo=fh, caption=text, parse_mode="HTML")
            # Оставляем у последнего сообщения кнопки возврата.
            await query.edit_message_reply_markup(reply_markup=None)
            return

        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
        return

    if data.startswith("cat:"):
        try:
            index = int(data.split(":", 1)[1])
        except ValueError:
            return
        category = get_category(index)
        if not category:
            await query.edit_message_text(
                "Раздел не найден.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Назад", callback_data="home")]]
                ),
            )
            return
        header = (
            f"{category.get('emoji', '')} {category.get('title', '')}\n\n"
            f"{category.get('description', '')}"
        ).strip()
        await query.edit_message_text(
            header, reply_markup=category_keyboard(index)
        )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "Не задан токен бота. Вставьте его в config.py "
            "или в переменную окружения TELEGRAM_BOT_TOKEN."
        )

    CONTENT.update(load_content())
    GUIDES.update(load_guides())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(CallbackQueryHandler(on_button))

    logger.info("Бот запущен. Разделов: %s", len(get_categories()))

    # Режим GitHub Actions: бот живёт ограниченное время и останавливается
    # сам (SIGTERM обрабатывается корректно, недоставленные апдейты Telegram
    # подхватит следующий запуск воркфлоу).
    max_runtime = int(os.environ.get("BOT_MAX_RUNTIME", "0") or 0)
    if max_runtime > 0:
        def _stop() -> None:
            logger.info("Лимит времени (%s с) — остановка бота.", max_runtime)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Timer(max_runtime, _stop).start()

    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except (TimedOut, RetryAfter, NetworkError, RuntimeError) as exc:
        # Ошибка характерна для принудительной остановки по таймеру:
        # в этот момент может быть оборван long-poll запрос.
        logger.info("Остановка бота (%s).", exc)
        raise SystemExit(0) from None
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise SystemExit(0) from None
    except TelegramError:
        logger.exception("Ошибка Telegram API при работе бота")
        raise


if __name__ == "__main__":
    main()
