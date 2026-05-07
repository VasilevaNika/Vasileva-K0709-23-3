# MinIO в Dating Bot — подробное описание

## Что такое MinIO и зачем он нужен

**MinIO** — это S3-совместимое объектное хранилище с открытым исходным кодом.
«S3-совместимое» означает, что оно реализует тот же API, что и Amazon S3, поэтому
любой код, написанный для S3, работает с MinIO без изменений.

В контексте Dating Bot MinIO решает конкретную проблему: **постоянное хранение
фотографий профилей**, независимое от Telegram.

### Проблема без MinIO

Когда пользователь отправляет фото боту, Telegram присваивает ему `file_id` —
идентификатор в системе Telegram. Проблемы с `file_id`:

1. `file_id` работает только внутри бота — другой бот или веб-приложение не
   может использовать этот идентификатор для получения фото.
2. Telegram не гарантирует вечное хранение файлов — `file_id` может стать
   недоступным со временем.
3. Фото нельзя обработать (изменить размер, конвертировать) без его скачивания.

### Решение с MinIO

```
Пользователь → фото → Telegram → бот скачивает → MinIO (постоянное хранение)
                                                         ↓
                                           Публичный URL → Telegram показывает
```

Фото хранится в MinIO как первичный источник. В базе данных сохраняется и
`file_id` (быстрый доступ через Telegram), и `storage_key` (путь в MinIO).
При показе профиля бот использует MinIO URL — Telegram сам скачивает фото
с MinIO и кэширует его.

---

## Архитектура хранения

### Схема данных

В таблице `profile_photos` есть два поля для фото:

```sql
file_id     VARCHAR(200)  -- Telegram file_id (быстрый доступ)
storage_key VARCHAR(500)  -- Путь в MinIO: "photos/abc123def456.jpg"
```

`storage_key` зарезервировали ещё на этапе проектирования модели (видно в
`app/models.py:71`). MinIO-интеграция теперь заполняет это поле реальным значением.

### Структура хранилища

```
MinIO-сервер (localhost:9000)
└── bucket: dating-photos          ← один bucket для всего проекта
    └── photos/                    ← директория для фото
        ├── 3f7a2b1c4d5e6f7a.jpg   ← имена генерируются как uuid4().hex
        ├── 8b9c0d1e2f3a4b5c.jpg
        └── ...
```

Bucket называется `dating-photos` (настраивается через `MINIO_BUCKET`).
Политика доступа — **public-read**: фото доступны по прямому URL без авторизации.

### URL фотографии

```
http://localhost:9000/dating-photos/photos/3f7a2b1c4d5e6f7a.jpg
^      ^              ^             ^
схема  MinIO-сервер   bucket        storage_key
```

Когда MinIO запущен в Docker Compose, снаружи (с хост-машины) он доступен по
`localhost:9000`. Внутри Docker-сети — `minio:9000`.

---

## Файлы проекта

### `app/services/storage.py` — основной класс

```
MinIOStorage
├── ensure_bucket()      — создать bucket при старте (если не существует)
├── upload_photo(bytes)  — загрузить фото, вернуть storage_key
├── get_public_url(key)  — прямой публичный URL (без срока действия)
├── get_presigned_url()  — временная подписанная ссылка (для приватных bucket)
└── delete(key)          — удалить объект из MinIO
```

#### Синхронный SDK + `asyncio.to_thread()`

Официальный Python SDK MinIO (`minio` пакет) — синхронный. В проекте используется
`asyncio.to_thread()` для запуска синхронных операций в отдельном потоке, чтобы
не блокировать event loop aiogram:

```python
async def upload_photo(self, data: bytes) -> str:
    def _sync():                              # ← синхронная операция
        self._client.put_object(...)

    await asyncio.to_thread(_sync)            # ← запуск в пуле потоков
```

`asyncio.to_thread()` — стандартная функция Python 3.9+. Она берёт свободный
поток из пула (`concurrent.futures.ThreadPoolExecutor`) и выполняет `_sync()` там.
Когда поток завершается, управление возвращается в event loop. Это не создаёт
новых потоков — пул управляется Python автоматически.

#### Два типа URL

| Метод | Когда использовать | Срок действия |
|-------|-------------------|---------------|
| `get_public_url()` | Bucket с политикой public-read | Бессрочно |
| `get_presigned_url()` | Приватный bucket | Настраиваемый (по умолчанию 1 час) |

В проекте используется `get_public_url()`, так как bucket настроен как публичный
через `mc anonymous set public` в `createbuckets` сервисе Docker Compose.

#### Устойчивость к ошибкам

`init_storage()` перехватывает все ошибки подключения и возвращает `None` если
MinIO недоступен:

```python
async def init_storage() -> Optional[MinIOStorage]:
    try:
        storage = MinIOStorage()
        await storage.ensure_bucket()
        return storage
    except Exception as exc:
        logger.error("MinIO недоступен: %s", exc)
        return None  # Бот продолжает работу без MinIO
```

Если `init_storage()` вернул `None`, бот работает в режиме без MinIO: фото
сохраняются только через Telegram `file_id`.

---

### `app/config.py` — настройки MinIO

```python
minio_endpoint: str = "localhost:9000"   # хост:порт без схемы
minio_access_key: str = "minioadmin"     # логин (как AWS Access Key)
minio_secret_key: str = "minioadmin"     # пароль (как AWS Secret Key)
minio_bucket: str = "dating-photos"      # имя bucket
minio_secure: bool = False               # False = HTTP, True = HTTPS
```

Все значения переопределяются через `.env` или переменные окружения Docker.

---

### `app/middleware.py` — `StorageMiddleware`

```python
class StorageMiddleware(BaseMiddleware):
    def __init__(self, storage: Optional[MinIOStorage]):
        self._storage = storage

    async def __call__(self, handler, event, data):
        data["storage"] = self._storage   # ← инъекция в хендлеры
        return await handler(event, data)
```

Middleware — это паттерн «цепочка обязанностей» в aiogram. Каждый входящий
апдейт (сообщение, callback) проходит через цепочку middleware перед хендлером.
`StorageMiddleware` добавляет `storage` в словарь `data`, который aiogram
передаёт в хендлер как именованный параметр.

Если `storage=None` (MinIO недоступен), хендлеры получают `None` и gracefully
обходят MinIO-логику.

---

### `app/bot.py` — инициализация при старте

```python
# MinIO — объектное хранилище фотографий (опционально)
minio_storage = await init_storage()

# Подключаем middleware ко всем апдейтам
storage_mw = StorageMiddleware(minio_storage)
dp.message.middleware(storage_mw)
dp.callback_query.middleware(storage_mw)
```

Инициализация происходит один раз при запуске бота. `ensure_bucket()` внутри
`init_storage()` создаёт bucket если он не существует — это защита от ситуации,
когда MinIO запустился, но bucket ещё не создан `createbuckets` контейнером.

---

### `app/handlers/registration.py` — загрузка фото

Шаг 7 регистрации — загрузка фотографии. Хендлер `process_photo_upload`:

```python
async def process_photo_upload(
    message: Message,
    state: FSMContext,
    bot: Bot,
    storage: Optional[MinIOStorage] = None,   # ← инъектируется middleware
):
    file_id = message.photo[-1].file_id       # Telegram file_id

    storage_key = None
    if storage is not None:
        try:
            # Скачиваем фото с серверов Telegram
            photo_bytes_io = await bot.download(file_id)
            # Загружаем в MinIO, получаем storage_key
            storage_key = await storage.upload_photo(photo_bytes_io.read())
        except Exception as exc:
            logger.warning("Не удалось загрузить в MinIO: %s", exc)

    # Сохраняем оба идентификатора в FSM-состоянии
    await state.update_data(photo_file_id=file_id, photo_storage_key=storage_key)
```

В финальном шаге регистрации (`process_pref_city`), где сохраняется профиль:

```python
await repo.add_photo(
    profile.id,
    photo_file_id,
    storage_key=data.get("photo_storage_key"),  # ← сохраняем в БД
)
```

Метод `bot.download(file_id)` из aiogram скачивает файл с серверов Telegram и
возвращает `BytesIO` объект. Это занимает сетевой запрос, но выполняется
асинхронно (не блокирует event loop).

---

### `app/handlers/feed.py` и `app/handlers/profile.py` — отображение фото

При показе карточки профиля (в ленте и в «Мой профиль»):

```python
# Определяем источник фото
photo_source: str = photos[0].file_id          # запасной вариант

if storage is not None and photos[0].storage_key:
    # MinIO доступен + фото загружено в MinIO
    photo_source = storage.get_public_url(photos[0].storage_key)
    # Например: "http://localhost:9000/dating-photos/photos/abc123.jpg"

await callback.message.answer_photo(photo=photo_source, ...)
```

Telegram принимает в `answer_photo` как `file_id`, так и прямой URL. Когда
передаётся URL, Telegram сам скачивает изображение с MinIO и кэширует его.

**Приоритет источников:**
1. MinIO публичный URL — если `storage_key` есть в БД и MinIO доступен
2. Telegram `file_id` — резервный вариант (работает даже без MinIO)

---

## Docker Compose

### Сервис `minio`

```yaml
minio:
  image: minio/minio:latest
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: minioadmin      # логин для S3 API и консоли
    MINIO_ROOT_PASSWORD: minioadmin  # пароль
  ports:
    - "9000:9000"   # S3 API
    - "9001:9001"   # Web Console
```

`server /data` — запуск MinIO в режиме одного узла (single-node). `/data` —
директория внутри контейнера, примонтирована через volume `miniodata`.

`--console-address ":9001"` — веб-консоль MinIO. Открывается в браузере по
адресу `http://localhost:9001`. Там можно визуально смотреть загруженные фото,
создавать bucket-ы, управлять политиками.

**Healthcheck:**
```yaml
test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:9000/minio/health/live || exit 1"]
```

Endpoint `/minio/health/live` — встроенная проверка состояния MinIO. Возвращает
HTTP 200 если сервер работает, иначе ошибку. Другие сервисы ждут `condition:
service_healthy` перед стартом.

### Сервис `createbuckets`

```yaml
createbuckets:
  image: minio/mc:latest       # MinIO Client — утилита командной строки
  depends_on:
    minio:
      condition: service_healthy
  entrypoint: >
    /bin/sh -c "
    mc alias set local http://minio:9000 minioadmin minioadmin;
    mc mb local/dating-photos --ignore-existing;
    mc anonymous set public local/dating-photos;
    "
```

`minio/mc` — официальный клиент MinIO. Три команды:

1. `mc alias set local ...` — добавить MinIO-сервер в список алиасов под именем `local`
2. `mc mb local/dating-photos --ignore-existing` — создать bucket `dating-photos`
   (`--ignore-existing` — не падать если уже существует)
3. `mc anonymous set public local/dating-photos` — установить политику public-read
   (фото доступны по прямому URL без авторизации)

Контейнер запускается один раз, выполняет команды и завершается (`restart: no`
по умолчанию). Это стандартный паттерн «init container» в Docker Compose.

### Зависимости сервисов

```
minio
  └── createbuckets (ждёт minio healthy, затем создаёт bucket и завершается)
  └── celery_worker (ждёт minio healthy, использует MinIOStorage)
  └── celery_beat   (ждёт minio healthy)
```

Бот (`app.bot`) работает локально и подключается к MinIO на `localhost:9000`.

---

## Полный поток загрузки фото

```
1. Пользователь → отправляет фото боту
        │
        ▼
2. Telegram принимает фото → присваивает file_id
        │
        ▼
3. process_photo_upload (registration.py)
        │  bot.download(file_id) → скачивает байты с Telegram
        │
        ▼
4. storage.upload_photo(bytes)
        │  asyncio.to_thread(_sync) → minio SDK.put_object()
        │  → MinIO сохраняет файл
        │  ← возвращает storage_key = "photos/abc123.jpg"
        │
        ▼
5. state.update_data(
        photo_file_id=file_id,
        photo_storage_key="photos/abc123.jpg"
   )
        │
        ▼
6. Финальный шаг регистрации → repo.add_photo(profile_id, file_id, storage_key)
        │  INSERT INTO profile_photos
        │    (profile_id, file_id,    storage_key)
        │  VALUES
        │    (42,         "AgAC...",  "photos/abc123.jpg")
        │
        ▼
7. Когда другой пользователь смотрит ленту:
        │  photos[0].storage_key = "photos/abc123.jpg"
        │  photo_source = storage.get_public_url(storage_key)
        │               = "http://localhost:9000/dating-photos/photos/abc123.jpg"
        │
        ▼
8. answer_photo(photo=photo_source)
        │  Telegram скачивает фото с MinIO по URL
        │  Показывает в чате
```

---

## Переменные окружения

| Переменная | Значение (dev) | Значение (Docker) | Описание |
|-----------|----------------|-------------------|----------|
| `MINIO_ENDPOINT` | `localhost:9000` | `minio:9000` | Хост:порт MinIO без схемы |
| `MINIO_ACCESS_KEY` | `minioadmin` | `minioadmin` | Логин (аналог AWS Access Key) |
| `MINIO_SECRET_KEY` | `minioadmin` | `minioadmin` | Пароль (аналог AWS Secret Key) |
| `MINIO_BUCKET` | `dating-photos` | `dating-photos` | Имя bucket |
| `MINIO_SECURE` | `false` | `false` | `true` если HTTPS |

**Почему разные endpoint для dev и Docker?**

Локально бот запускается вне Docker, поэтому MinIO доступен через mapped port
`localhost:9000`. Внутри Docker-сети сервисы обращаются друг к другу по имени
сервиса `minio:9000`.

---

## Веб-консоль MinIO

После запуска `docker compose up` откройте браузер:

```
http://localhost:9001
Логин:    minioadmin
Пароль:   minioadmin
```

В консоли можно:
- Смотреть загруженные фотографии в `dating-photos/photos/`
- Скачивать и удалять объекты
- Управлять политиками доступа
- Мониторить статистику использования

---

## Ответы на типовые вопросы преподавателя

**Q: Почему MinIO, а не Amazon S3?**  
A: MinIO S3-совместим — код работает одинаково с обоими. Для учебного проекта
MinIO предпочтительнее: запускается локально в Docker, не требует AWS-аккаунта,
бесплатен. При деплое на продакшн достаточно поменять `MINIO_ENDPOINT` на S3 URL.

**Q: Почему `asyncio.to_thread()`, а не `async`-версия SDK?**  
A: Официальный Python SDK MinIO (`minio`) синхронный. `asyncio.to_thread()`
запускает синхронную функцию в пуле потоков, не блокируя основной event loop.
Это стандартный паттерн для работы с sync-библиотеками в async-коде. Существуют
async-обёртки (`miniopy-async`, `aioboto3`), но они добавляют зависимость и
сложность без значимого прироста производительности для нашего масштаба.

**Q: Что происходит если MinIO недоступен?**  
A: `init_storage()` перехватывает ошибку и возвращает `None`. `StorageMiddleware`
передаёт `None` в хендлеры. Хендлеры проверяют `if storage is not None:` перед
любым обращением к MinIO. Бот продолжает работу в режиме без MinIO: фото
отображаются через Telegram `file_id`. Это называется **graceful degradation** —
система деградирует, но не падает.

**Q: Почему bucket публичный?**  
A: Для упрощения. Фото анкет в dating-сервисе не содержат секретов — они
намеренно публичны. Публичный bucket позволяет использовать прямые URL без
presigned-ссылок (которые истекают). Если нужна приватность, замените
`get_public_url()` на `get_presigned_url()` и уберите `mc anonymous set public`.

**Q: Зачем хранить и `file_id`, и `storage_key`?**  
A: Две стратегии резервирования:
- `file_id` — быстрый доступ через Telegram CDN, работает без MinIO
- `storage_key` — постоянное хранение, работает без Telegram (например, в
  будущем веб-интерфейсе)
Оба поля заполняются при загрузке, система использует MinIO если доступен.

**Q: Что такое presigned URL и зачем он нужен?**  
A: Это URL с встроенной цифровой подписью (HMAC-SHA256). Без знания секретного
ключа URL нельзя подделать или угадать. Он содержит параметры: кто выдал доступ,
к какому объекту, на сколько времени. Используется для приватных bucket-ов, где
прямой доступ запрещён. В нашем случае (публичный bucket) presigned URL
избыточен, но `get_presigned_url()` реализован для демонстрации.

**Q: Как MinIO вписывается в архитектурную схему?**  
A: В `docs/02-architecture.md` есть диаграмма, где MinIO обозначен как `S3[(MinIO / S3)]`
и к нему идёт стрелка `API -.->|фото| S3`. Эта стрелка теперь реализована:
`registration.py` → `storage.upload_photo()` → MinIO. А показ анкет —
`feed.py/profile.py` → `storage.get_public_url()` → URL в Telegram.
