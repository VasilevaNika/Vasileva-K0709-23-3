# Celery и Redis в Dating Bot — подробное описание

## Зачем нужны Celery и Redis

В архитектуре проекта предусмотрены **фоновые вычисления**: рейтинг каждого
профиля (primary, behavior, combined) должен периодически пересчитываться, а
также обновляться сразу после того, как кто-то поставил лайк или пас.

Делать эти вычисления прямо внутри обработчика Telegram-бота нельзя — это
заблокирует ответ пользователю на сотни миллисекунд (а при большом числе
профилей — и на секунды). Решение: **выносить тяжёлые задачи в фон**.

Именно для этого существует **Celery** — система выполнения фоновых задач. Она
получает задачи через **брокер сообщений** (в нашем случае Redis), выполняет их
в отдельных процессах и при необходимости сохраняет результаты в **бэкенд
результатов** (тоже Redis).

---

## Роль Redis в проекте

Redis используется в двух разных ролях:

| Роль | База Redis | Кто использует | Что хранит |
|------|-----------|----------------|------------|
| **FeedCache** | DB 0 | `app/services/cache.py` | Списки profile_id для каждого пользователя (кэш ленты) |
| **Celery broker** | DB 1 | Celery | Очередь задач (какие задачи ждут выполнения) |
| **Celery result backend** | DB 2 | Celery | Результаты и статусы выполненных задач |

Разделение по номерам баз данных гарантирует, что данные не смешиваются и не
конфликтуют.

Redis уже был в проекте до добавления Celery (см. `docker-compose.yml` и
`app/services/cache.py`). Celery просто подключается к тому же Redis-серверу,
но использует другие DB-номера.

---

## Файлы, связанные с Celery

### `app/celery_app.py` — конфигурация Celery

Создаёт и настраивает объект `Celery`:

```python
celery_app = Celery(
    "dating_bot",
    broker=settings.celery_broker_url,    # redis://host:6379/1
    backend=settings.celery_result_backend, # redis://host:6379/2
    include=["app.tasks"],                # где искать задачи
)
```

Здесь же задаётся расписание периодических задач (Celery Beat):

```python
celery_app.conf.beat_schedule = {
    "refresh-all-ratings-every-10-min": {
        "task": "app.tasks.refresh_all_ratings",
        "schedule": crontab(minute="*/10"),  # каждые 10 минут
    },
}
```

**Зачем отдельный файл, а не прямо в `bot.py`?**  
Celery worker и beat запускаются как **отдельные процессы** (не вместе с ботом).
Когда Celery импортирует `app.celery_app`, ему нужен модуль, который определяет
только приложение Celery — без инициализации aiogram, базы данных и т.д.

---

### `app/tasks.py` — определения задач

Содержит две задачи:

#### Задача 1: `refresh_all_ratings`

```python
@shared_task(name="app.tasks.refresh_all_ratings", bind=True, max_retries=3)
def refresh_all_ratings(self):
    ...
```

- **Тип**: периодическая (планируется Celery Beat раз в 10 минут)
- **Что делает**: запрашивает все профили из PostgreSQL, для каждого вызывает
  `refresh_profile_rating()` из `app/services/ranking.py`, сохраняет результаты
  в таблицу `profile_ratings`
- **Зачем**: поведенческий рейтинг (`behavior_score`) зависит от числа лайков,
  мэтчей и активности чатов — эти данные постоянно меняются. Плановый пересчёт
  гарантирует, что рейтинги в БД не устареют более чем на 10 минут
- **Параметры отказоустойчивости**: `max_retries=3`, `default_retry_delay=60` —
  если задача упала, Celery повторит её до трёх раз с паузой 60 секунд

#### Задача 2: `update_profile_rating`

```python
@shared_task(name="app.tasks.update_profile_rating", bind=True, max_retries=3)
def update_profile_rating(self, profile_id: int):
    ...
```

- **Тип**: событийная (вызывается вручную из кода бота после каждого свайпа)
- **Что делает**: находит в БД один конкретный профиль по `profile_id` и
  пересчитывает его рейтинг
- **Зачем**: если ждать планового пересчёта (до 10 минут), то после серии
  лайков профиль может неточно ранжироваться в ленте других пользователей.
  Событийная задача актуализирует рейтинг мгновенно (в фоне)
- **Параметры**: `bind=True` — задача получает доступ к самой себе (объект
  `self`) для вызова `self.retry()` при ошибке

#### Паттерн «sync Celery + async SQLAlchemy»

Celery worker работает в **синхронном** режиме, а SQLAlchemy-код в проекте
**асинхронный** (asyncpg + async/await). Чтобы вызвать async-код из sync-задачи:

```python
def refresh_all_ratings(self):
    asyncio.run(_async_refresh_all_ratings())  # создаёт новый event loop

async def _async_refresh_all_ratings():
    engine, factory = _make_session_factory()  # новый движок для этого loop-а
    async with factory() as session:
        ...
    await engine.dispose()
```

Каждый вызов `asyncio.run()` создаёт **свой** event loop, и движок SQLAlchemy
создаётся внутри этого же loop-а. Это обязательное условие для корректной работы
`asyncpg` — соединения с БД не могут использоваться в другом event loop.

---

### `app/config.py` — настройки Celery

Добавлены два поля:

```python
celery_broker_url: str = "redis://localhost:6379/1"
celery_result_backend: str = "redis://localhost:6379/2"
```

Значения переопределяются через переменные окружения `CELERY_BROKER_URL` и
`CELERY_RESULT_BACKEND` (из `.env` или docker-compose).

---

### `app/handlers/feed.py` — точка вызова задачи

В обработчике свайпа (`handle_swipe`), после записи свайпа в БД:

```python
# Запускаем фоновый пересчёт рейтинга
update_profile_rating.delay(target_profile.id)
```

Метод `.delay(args)` — это стандартный способ **асинхронно** отправить задачу в
очередь Celery. Он немедленно возвращается (не ждёт выполнения задачи) и
практически не влияет на скорость ответа бота.

Под капотом `.delay()`:
1. Сериализует аргументы (`profile_id`) в JSON
2. Отправляет сообщение в Redis (DB 1)
3. Возвращает объект `AsyncResult` (мы его не используем, задача fire-and-forget)

Celery worker в это время слушает очередь и подхватывает задачу.

---

## docker-compose.yml — новые сервисы

### `celery_worker`

```yaml
celery_worker:
  build: .
  command: celery -A app.celery_app worker --loglevel=info --concurrency=2
  depends_on:
    postgres: { condition: service_healthy }
    redis:    { condition: service_healthy }
```

- Запускает 2 параллельных воркера (`--concurrency=2`)
- `depends_on` с `condition: service_healthy` гарантирует, что воркер стартует
  только после того, как Postgres и Redis полностью готовы к работе
- Использует те же переменные окружения, что и бот, но с хостами `postgres` и
  `redis` (имена сервисов внутри Docker-сети)

### `celery_beat`

```yaml
celery_beat:
  build: .
  command: celery -A app.celery_app beat --loglevel=info
  depends_on:
    - celery_worker
```

- **Планировщик** — отдельный лёгкий процесс, который в нужное время
  публикует задачи в очередь (например, `refresh_all_ratings` каждые 10 минут)
- Сам задачи **не выполняет** — только планирует; выполняет воркер
- Выделен в отдельный сервис, чтобы не конкурировать с воркером за ресурсы

---

## Поток данных: как работает пересчёт рейтинга

```
Пользователь нажимает ❤️ Лайк
       │
       ▼
handle_swipe() в feed.py
       │  1. Записывает swipe в PostgreSQL
       │  2. Проверяет взаимный лайк (мэтч?)
       │  3. update_profile_rating.delay(profile_id)  ←── отправляет в Redis
       │
       ▼
Бот отвечает пользователю (следующая анкета)

          Параллельно (в фоне):
          Redis DB1 (broker)
                │
                ▼
          celery_worker
                │  asyncio.run(_async_update_profile_rating)
                │  ├─ connect PostgreSQL
                │  ├─ SELECT profile WHERE id = ?
                │  ├─ compute_primary_score()
                │  ├─ compute_behavior_score()
                │  └─ UPDATE profile_ratings SET combined_score = ...
                │
                ▼
          Результат сохранён в Redis DB2 (result backend)
```

---

## Поток данных: периодический пересчёт (Celery Beat)

```
Каждые 10 минут:
celery_beat
    │  "refresh_all_ratings" → Redis DB1 (broker)
    │
    ▼
celery_worker
    │  asyncio.run(_async_refresh_all_ratings)
    │  ├─ SELECT все профили из PostgreSQL
    │  └─ для каждого: compute + UPDATE profile_ratings
    ▼
Все рейтинги актуальны
```

---

## Как запустить

### Локально (без Docker)

```bash
# Терминал 1 — воркер
celery -A app.celery_app worker --loglevel=info

# Терминал 2 — планировщик
celery -A app.celery_app beat --loglevel=info

# Терминал 3 — бот
python -m app.bot
```

### Через Docker Compose

```bash
docker compose up --build
```

Запускаются: `postgres`, `redis`, `celery_worker`, `celery_beat` (и отдельно бот
если добавить сервис `bot` в docker-compose).

---

## Зависимости

В `requirements.txt` добавлена строка:

```
celery[redis]>=5.3.0,<6.0
```

`celery[redis]` — это Celery с дополнительным пакетом `redis-py`, необходимым
для использования Redis в качестве брокера и бэкенда. Без этого суффикса Celery
установился бы без Redis-транспорта.

---

## Ответы на типовые вопросы преподавателя

**Q: Почему Redis, а не RabbitMQ или Kafka?**  
A: Redis уже был в проекте как кэш ленты анкет. Использовать его же как брокер
Celery — логичное решение: меньше зависимостей в инфраструктуре. RabbitMQ
предпочтительнее для высоких нагрузок и сложных маршрутов сообщений, Kafka —
для стриминга событий. Для учебного проекта Redis достаточен.

**Q: Почему Celery worker работает синхронно, если бот асинхронный?**  
A: Celery был создан до широкого распространения asyncio и по умолчанию
использует синхронные воркеры (процессы или потоки). В задачах мы вызываем
асинхронный код через `asyncio.run()`, что создаёт отдельный event loop для
каждой задачи — это корректный паттерн для изолированных фоновых задач.

**Q: Что произойдёт, если Redis недоступен?**  
A: Celery задачи не смогут быть поставлены в очередь (`.delay()` выбросит
исключение). В `feed.py` это не критично: бот продолжит работу (ответит
пользователю), а рейтинг обновится при следующем плановом запуске Celery Beat.

**Q: Чем Beat отличается от Worker?**  
A: Beat — **планировщик**: он смотрит на расписание и в нужный момент кладёт
задачу в Redis-очередь. Worker — **исполнитель**: он читает очередь и
выполняет задачи. Один Beat может обслуживать несколько Workers.

**Q: Зачем `bind=True` в декораторе задачи?**  
A: При `bind=True` первым аргументом задача получает `self` — ссылку на саму
себя. Это даёт доступ к методу `self.retry(exc=...)`, который позволяет
повторить задачу при ошибке, не выходя из неё явным исключением.

**Q: Где в архитектурной схеме проекта место Celery?**  
A: В файле `docs/02-architecture.md` описан блок «Рейтинг (фон)»:
«Периодически (Celery) или по событиям: пересчёт `primary_score`,
`behavior_score`, `combined_score` в `profile_ratings`». Именно это реализуют
задачи `refresh_all_ratings` и `update_profile_rating`.
