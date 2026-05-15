"""
Централизованная настройка логирования.

Три обработчика:
  - Консоль  (WARNING+) — только предупреждения и ошибки в stdout.
    Не перегружает вывод, но важное всегда видно.
  - logs/app.log  (INFO+) — все бизнес-события, ротация 10 МБ × 5 файлов.
    Основной журнал: регистрации, свайпы, мэтчи, чат, рейтинг.
  - logs/errors.log (ERROR+) — только ошибки, ротация 5 МБ × 3 файла.
    Удобно смотреть только проблемы, не листая всё подряд.

Формат строки:
  2026-01-15 14:32:05 | INFO     | app.handlers.feed              | Swipe | user_id=42 → profile_id=7 | action=like | remaining=27
"""

import logging
import logging.handlers
import os

LOG_DIR = "logs"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Настроить логирование при старте бота. Вызывается один раз из bot.py."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # root принимает всё, фильтруют обработчики

    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # ── Консоль: WARNING и выше ─────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)

    # ── app.log: INFO и выше, ротация 10 МБ, хранить 5 архивов ────────────
    app_file = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_file.setLevel(logging.INFO)
    app_file.setFormatter(formatter)

    # ── errors.log: только ERROR+, ротация 5 МБ, хранить 3 архива ─────────
    error_file = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "errors.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(app_file)
    root.addHandler(error_file)

    # Заглушаем шумные сторонние библиотеки — их DEBUG/INFO нам не нужны
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
