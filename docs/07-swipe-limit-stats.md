# 07 — Лимит свайпов и статистика

## Обзор

В проект добавлены две взаимосвязанные функции:

1. **Лимит свайпов** — каждый пользователь может сделать не более 30 свайпов в сутки. Счётчик сбрасывается автоматически в полночь без каких-либо cron-задач.
2. **Статистика** — отдельный экран с агрегированными данными: лайки, пасы, мэтчи, конверсия и остаток свайпов на день.

---

## Архитектура лимита свайпов

### Хранение в Redis

Счётчик хранится в Redis с составным ключом, включающим дату:

```
swipe_limit:{user_id}:{YYYY-MM-DD}
```

Пример: `swipe_limit:42:2026-05-06`

**Почему Redis, а не PostgreSQL:**
- Инкремент атомарен (`INCR`) — защита от гонок при одновременных запросах
- TTL на уровне Redis заменяет cron: ключ исчезает сам в момент наступления следующего дня
- Нулевая нагрузка на БД при каждом свайпе

### TTL до полуночи

```python
def _ttl_until_midnight(self) -> int:
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max(1, int((midnight - now).total_seconds()))
```

При первом свайпе дня ключ создаётся и получает TTL = секунды до 00:00:00 следующего дня. В полночь Redis удаляет ключ — лимит сброшен автоматически.

### Класс SwipeLimiter

**Файл:** `app/services/swipe_limit.py`

```python
DAILY_SWIPE_LIMIT = 30

class SwipeLimiter:
    async def get_used(self, user_id: int) -> int: ...
    async def increment(self, user_id: int) -> int: ...
    async def is_limit_reached(self, user_id: int) -> bool: ...
    async def remaining(self, user_id: int) -> int: ...
```

| Метод | Описание |
|---|---|
| `get_used` | Сколько свайпов использовано сегодня |
| `increment` | Увеличить счётчик на 1 (вызывается после успешного свайпа) |
| `is_limit_reached` | `True` если использовано ≥ 30 |
| `remaining` | Сколько свайпов осталось |

### Инъекция через Middleware

**Файл:** `app/middleware.py`

```python
class SwipeLimiterMiddleware(BaseMiddleware):
    def __init__(self, limiter: SwipeLimiter):
        self._limiter = limiter

    async def __call__(self, handler, event, data):
        data["swipe_limiter"] = self._limiter
        return await handler(event, data)
```

Экземпляр `SwipeLimiter` создаётся один раз в `bot.py` и передаётся в каждый хендлер как параметр `swipe_limiter`. Это тот же паттерн, что используется для `FeedCache` и `MinIOStorage`.

---

## Интеграция в ленту анкет

**Файл:** `app/handlers/feed.py`

### Точки проверки лимита

**1. При открытии ленты (`open_feed`):**
```python
if await swipe_limiter.is_limit_reached(user.id):
    await callback.message.answer("⏳ Лимит свайпов исчерпан...")
    return
```

**2. При обработке свайпа (`handle_swipe`):**
```python
if await swipe_limiter.is_limit_reached(viewer_user.id):
    await callback.answer("⏳ Лимит исчерпан. Возвращайтесь завтра!", show_alert=True)
    return

# После успешной записи свайпа:
await swipe_limiter.increment(viewer_user.id)
```

Двойная проверка нужна потому что пользователь может нажать кнопку свайпа на уже открытой карточке, когда лимит исчерпался в другой сессии.

### Отображение остатка в карточке

Количество оставшихся свайпов выводится в подписи к фото/тексту карточки:

```
👤 Иван, 24 года
📍 Москва
...

🔄 Осталось свайпов сегодня: 17/30
```

Сигнатура `show_profile_card` расширена параметром `remaining_swipes: int | None`:
```python
async def show_profile_card(
    callback, profile_id, repo,
    storage=None,
    remaining_swipes: int | None = None,
) -> None:
    ...
    if remaining_swipes is not None:
        caption += f"\n\n🔄 Осталось свайпов сегодня: {remaining_swipes}/{DAILY_SWIPE_LIMIT}"
```

---

## Статистика пользователя

### SQL-запросы в репозитории

**Файл:** `app/repository.py`, метод `get_user_stats()`

Выполняет 4 агрегирующих запроса к таблице `swipes` и `matches`:

```python
async def get_user_stats(self, user_id: int) -> dict:
    # SELECT COUNT(*) FROM swipes WHERE from_user_id = ? AND action = 'like'
    likes_sent = ...

    # SELECT COUNT(*) FROM swipes WHERE from_user_id = ? AND action = 'pass'
    passes_sent = ...

    # SELECT COUNT(*) FROM swipes WHERE to_user_id = ? AND action = 'like'
    likes_received = ...

    # SELECT COUNT(*) FROM matches WHERE user_a_id = ? OR user_b_id = ?
    matches = ...

    match_rate = round(matches / likes_sent * 100, 1) if likes_sent > 0 else 0.0

    return {
        "likes_sent": likes_sent,
        "passes_sent": passes_sent,
        "likes_received": likes_received,
        "matches": matches,
        "match_rate": match_rate,
    }
```

Все запросы выполняются к **существующим таблицам** — новых таблиц не требуется.

### Хендлер статистики

**Файл:** `app/handlers/stats.py`

Доступен по кнопке «📊 Статистика» в главном меню (callback `menu:stats`).

Пример отображения:
```
📊 Ваша статистика

👍 Лайков отправлено: 47
👎 Пасов отправлено: 12
❤️ Лайков получено: 23
🎉 Мэтчей: 8
📈 Конверсия лайк → мэтч: 17.0%

🔄 Свайпов сегодня: 5/30
⏳ Осталось свайпов: 25

📅 Дней в сервисе: 14
```

---

## Изменённые файлы

| Файл | Изменение |
|---|---|
| `app/services/swipe_limit.py` | **Новый.** Класс `SwipeLimiter` с Redis-счётчиком |
| `app/handlers/stats.py` | **Новый.** Хендлер экрана статистики |
| `app/repository.py` | Добавлен метод `get_user_stats()` |
| `app/middleware.py` | Добавлен `SwipeLimiterMiddleware` |
| `app/handlers/feed.py` | Проверка лимита в `open_feed` и `handle_swipe`; остаток в карточке |
| `app/handlers/main.py` | Кнопка «📊 Статистика» в главном меню |
| `app/handlers/__init__.py` | Экспорт `register_stats_router` |
| `app/bot.py` | Создание `SwipeLimiter`, подключение `SwipeLimiterMiddleware`, регистрация роутера |

---

## Конфигурация

Лимит вынесен в константу:

```python
# app/services/swipe_limit.py
DAILY_SWIPE_LIMIT = 30
```

Чтобы изменить лимит — достаточно поменять одно число. Никаких миграций БД не требуется.

---

## Схема потока при свайпе

```
Пользователь нажимает ❤️ / 👎
        ↓
handle_swipe в feed.py
        ↓
swipe_limiter.is_limit_reached(user_id)
    ├── True  → show_alert "Лимит исчерпан" → return
    └── False ↓
              repo.record_swipe(...)  ← запись в PostgreSQL
              swipe_limiter.increment(user_id)  ← INCR в Redis
              ↓
         remaining = swipe_limiter.remaining(user_id)
              ├── 0 → сообщение "Лимит исчерпан, до завтра"
              └── > 0 → show_profile_card(..., remaining_swipes=remaining)
```

---

## Запуск без изменений инфраструктуры

Новый функционал использует тот же Redis-экземпляр (DB 0), что и `FeedCache`. Дополнительных сервисов, миграций или переменных окружения не требуется.
