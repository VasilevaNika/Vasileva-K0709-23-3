# Отчёт по дополнительному функционалу

---

## 1. Система чатов при мэтче

**Файлы:** `app/models.py`, `app/repository.py`, `app/handlers/matches.py`

**Технологии:** SQLAlchemy (PostgreSQL), aiogram FSM

**Реализация:**

В `models.py` создана таблица `messages` — хранит `match_id`, `sender_id` (FK на users), `body`, `sent_at`.

В `repository.py` два метода:
- `send_message(match_id, sender_id, body)` — сохраняет сообщение в БД
- `get_messages(match_id, limit=20)` — достаёт последние N сообщений, сортировка по `sent_at`

В `handlers/matches.py` реализован FSM-поток через `ChatStates(StatesGroup)` с состоянием `in_chat`:
1. Пользователь открывает список мэтчей → кнопка «💬 Написать» вызывает `chat:open:{match_id}`
2. Хендлер `open_chat` находит мэтч в БД, грузит историю последних 10 сообщений, переводит пользователя в состояние `ChatStates.in_chat` и сохраняет в FSM `match_id` и `partner_telegram_id`
3. Все текстовые сообщения в состоянии `in_chat` перехватывает хендлер `relay_message` — он сохраняет сообщение в БД и пересылает партнёру через `bot.send_message(partner_telegram_id, ...)`
4. Выход из чата — команда `/stopchat`, которая вызывает `state.clear()`

---

## 2. Статистика профиля по кнопке «Статистика»

**Файлы:** `app/handlers/stats.py`, `app/repository.py`, `app/services/swipe_limit.py`

**Технологии:** SQLAlchemy (агрегатные запросы), Redis

**Реализация:**

В `repository.py` метод `get_user_stats(user_id)` выполняет 4 отдельных SQL-запроса через `func.count()`:
- `likes_sent` — `COUNT` свайпов где `from_user_id = user_id AND action = 'like'`
- `passes_sent` — то же с `action = 'pass'`
- `likes_received` — `COUNT` свайпов где `to_user_id = user_id AND action = 'like'`
- `matches` — `COUNT` мэтчей где `user_a_id = user_id OR user_b_id = user_id`
- `match_rate` — вычисляется на Python: `matches / likes_sent * 100`

В `handlers/stats.py` хендлер `show_stats` дополнительно получает остаток свайпов через `swipe_limiter.remaining(user_id)` (из Redis) и считает дни в сервисе как `(date.today() - user.created_at.date()).days`. Всё собирается в одно сообщение.

---

## 3. Ограничение на 30 свайпов в день

**Файлы:** `app/services/swipe_limit.py`, `app/handlers/feed.py`, `app/middleware.py`

**Технологии:** Redis (redis.asyncio), aiogram Middleware

**Реализация:**

Класс `SwipeLimiter` в `swipe_limit.py`:
- Ключ в Redis: `swipe_limit:{user_id}:{YYYY-MM-DD}` — один ключ на пользователя на день
- TTL ключа устанавливается при первом свайпе = секунды до полуночи (`_ttl_until_midnight()`). Сброс счётчика автоматический, cron не нужен
- `increment(user_id)` — атомарно увеличивает счётчик через Redis `INCR`, при первом вызове (`count == 1`) выставляет TTL
- `is_limit_reached(user_id)` — проверяет `used >= 30`
- `remaining(user_id)` — возвращает `max(0, 30 - used)`

В `handlers/feed.py`:
- При открытии ленты и при каждом свайпе вызывается `is_limit_reached()`. Если лимит исчерпан — сообщение «Возвращайтесь завтра» и выход
- После записи свайпа в БД вызывается `swipe_limiter.increment()`
- Остаток свайпов показывается под каждой карточкой анкеты

В `middleware.py` класс `SwipeLimiterMiddleware` внедряет `SwipeLimiter` в хендлеры через `data["swipe_limiter"]`.

---

## 4. Логирование

**Файлы:** `app/logging_config.py`, `app/bot.py`, `app/handlers/feed.py`, `app/handlers/matches.py`, `app/handlers/registration.py`, `app/services/ranking.py`

**Технологии:** Python `logging`, `logging.handlers.RotatingFileHandler`

**Реализация:**

В `logging_config.py` создана функция `setup_logging()`, которая вызывается один раз при старте бота. Настраиваются три обработчика:

- **Консоль** — уровень `WARNING` и выше. Не заливает вывод в prod, только важные предупреждения и ошибки
- **`logs/app.log`** — уровень `INFO` и выше, ротация по размеру: 10 МБ на файл, хранить 5 архивов (`RotatingFileHandler`). Основной журнал бизнес-событий
- **`logs/errors.log`** — только `ERROR` и выше, ротация 5 МБ × 3 файла. Отдельный файл для быстрого поиска проблем без листания всего лога

Формат строки одинаков во всех файлах:
```
2026-01-15 14:32:05 | INFO     | app.handlers.feed              | Swipe | user_id=42 → profile_id=7 | action=like | daily_count=3/30
```

Сторонние библиотеки (aiogram, aiohttp, sqlalchemy) принудительно переведены на уровень `WARNING` — их отладочный вывод не нужен.

Бизнес-события, которые пишутся в лог:

- **Свайп** (`feed.py`) — `user_id`, `profile_id`, `action`, сколько свайпов использовано сегодня из 30
- **Лимит свайпов** (`feed.py`) — когда пользователь упирается в лимит, до и во время свайпа
- **Мэтч** (`feed.py`) — `match_id`, оба `user_id`
- **Открытие чата** (`matches.py`) — `user_id`, `match_id`, `partner_user_id`
- **Отправка сообщения** (`matches.py`) — `match_id`, `sender_id`, длина сообщения в символах
- **Ошибка доставки сообщения** (`matches.py`) — уровень `ERROR` с полным контекстом
- **Завершение регистрации** (`registration.py`) — `user_id`, `display_name`, процент заполненности анкеты
- **Производительность ранжирования** (`ranking.py`) — сколько кандидатов оценено, сколько возвращено, время выполнения в секундах
- **Celery недоступен** (`feed.py`) — уровень `WARNING` с указанием `profile_id` и текстом ошибки