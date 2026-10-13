"""Конфигурация бота.

Токен читается в порядке приоритета:
1. Переменная окружения TELEGRAM_BOT_TOKEN (её задаёт GitHub Actions)
2. Переменная BOT_TOKEN из local_config.py (для локального запуска;
   этот файл в .gitignore и в репозиторий не попадает)
"""

import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

try:
    from local_config import BOT_TOKEN as _LOCAL_BOT_TOKEN

    BOT_TOKEN = BOT_TOKEN or _LOCAL_BOT_TOKEN
except ImportError:
    pass

# UID владельца бота — только ему доступна команда /reload.
# Узнать свой UID: напишите боту @userinfobot.
OWNER_ID = 0
