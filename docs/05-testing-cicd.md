# Тесты и CI/CD — подробное описание

## Зачем нужны тесты

Тесты позволяют убедиться, что каждая функция системы работает именно так, как
ожидается — не только сейчас, но и после любых будущих изменений. Без тестов
при каждом изменении кода нужно вручную проверять все сценарии, что долго и
ненадёжно.

## Зачем нужен CI/CD

**CI (Continuous Integration)** — автоматически запускает линтер и тесты при
каждом `git push`. Если что-то сломалось, GitHub сразу показывает красный
значок, а не ты узнаёшь об этом на защите.

**CD (Continuous Delivery)** — автоматически собирает Docker-образ при каждом
push, проверяя что `Dockerfile` корректен и все зависимости устанавливаются.

---

## Технологии тестирования

| Библиотека | Роль | Почему |
|-----------|------|--------|
| `pytest` | Тест-раннер | Де-факто стандарт Python-тестирования |
| `pytest-asyncio` | Поддержка `async def` тестов | Весь проект асинхронный (aiogram, SQLAlchemy async) |
| `aiosqlite` | SQLite in-memory вместо PostgreSQL | Тесты не требуют запущенного сервера БД |
| `fakeredis` | In-memory Redis для тестов FeedCache | Тесты не требуют запущенного Redis |

---

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py          — общие фикстуры (db_engine, db_session)
├── test_repository.py   — тесты CRUD-операций UserRepository
├── test_ranking.py      — тесты алгоритма ранжирования
├── test_cache.py        — тесты Redis-кэша ленты (FeedCache)
└── test_tasks.py        — тесты Celery-задач
```

---

## Файл `tests/conftest.py`

Содержит **фикстуры** — переиспользуемые блоки подготовки/очистки для тестов.

```python
os.environ.setdefault("BOT_TOKEN", "test_token_not_real")
```

Ставится до любых импортов `app.*`, потому что `pydantic-settings` проверяет
наличие `BOT_TOKEN` при создании объекта `Settings()` — если его нет, упадёт
ошибка валидации ещё до запуска тестов.

```python
@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    ...
    await engine.dispose()
```

`StaticPool` — пул из одного соединения. SQLite in-memory работает только в
рамках одного соединения; без `StaticPool` каждый `async with session()` открыл
бы новое соединение → новую пустую БД, и тест бы не увидел данные.

`check_same_thread=False` — SQLite по умолчанию запрещает использование
соединения из другого потока. asyncio может переключаться между потоками, поэтому
отключаем эту проверку.

---

## Файл `tests/test_repository.py`

Тестирует **UserRepository** — все CRUD-операции без моков (напрямую с SQLite).

### Классы тестов

#### `TestUserCRUD`
- `test_create_user_sets_defaults` — новый пользователь создаётся с `is_active=True`, `is_registered=False`
- `test_get_or_create_user_returns_is_new_true` — первый вызов → `is_new=True`
- `test_get_or_create_user_returns_existing` — повторный вызов → `is_new=False`, тот же `id`
- `test_get_user_by_telegram_id_not_found` — несуществующий `telegram_id` → `None`

#### `TestProfileCRUD`
- `test_save_profile_creates_record` — все поля сохраняются, `profile_completeness > 0`
- `test_save_profile_marks_user_registered` — после `save_profile` пользователь помечается `is_registered=True`
- `test_save_profile_upsert_updates_name` — повторный вызов обновляет данные (не дублирует)
- `test_add_photo_increments_sort_order` — фотографии нумеруются последовательно: 1, 2, 3...
- `test_get_photos_returns_ordered` — фотографии возвращаются в правильном порядке

#### `TestCompleteness`
Тестирует **статический метод** `_calculate_completeness` без БД:
- пустой профиль → 0
- все поля заполнены → 100
- только имя → 15 (вес поля `display_name`)
- короткое bio (<10 символов) → не засчитывается
- много фото → максимум 10 баллов (ограничение)

#### `TestSwipes`
- `test_record_swipe_like` — свайп записывается в БД
- `test_check_mutual_like_both_liked` — оба поставили лайк → `True`
- `test_check_mutual_like_one_sided` — только один лайк → `False`
- `test_check_mutual_like_pass_does_not_count` — пас не считается лайком

#### `TestMatches`
- `test_create_match_canonical_order` — всегда `user_a_id < user_b_id` независимо от порядка аргументов
- `test_get_match_returns_existing` — можно найти созданный мэтч
- `test_get_user_matches_returns_all` — все мэтчи пользователя возвращаются
- `test_get_partner_user_id` — корректно определяет партнёра для обеих сторон мэтча

---

## Файл `tests/test_ranking.py`

Тестирует **алгоритм ранжирования** (три уровня рейтинга).

### Классы тестов

#### `TestPrimaryScore`
- `test_empty_profile_has_low_score` — незаполненный профиль → низкий балл
- `test_full_profile_gets_maximum_no_prefs` — полный профиль с фото → ≥45 баллов
- `test_score_is_within_range` — результат всегда от 0 до 100
- `test_gender_match_increases_score` — совпадение пола предпочтений добавляет баллы

#### `TestBehaviorScore`
- `test_new_profile_gets_neutral_score_30` — **новый профиль без свайпов → ровно 30.0** (нейтральный балл из кода)
- `test_liked_profile_gets_more_than_30` — профиль с лайками от других → >30
- `test_all_passes_gives_low_behavior` — только пасы от других → <30
- `test_score_is_within_range` — результат 0..100

#### `TestCombinedScore`
- `test_combined_equals_weighted_sum` — `combined = 0.4 * primary + 0.6 * behavior` (константы из кода)
- `test_all_scores_in_range` — все три компоненты в диапазоне 0..100

#### `TestRefreshProfileRating`
- `test_creates_profile_rating_row` — функция создаёт запись в таблице `profile_ratings`
- `test_updates_existing_rating` — повторный вызов обновляет ту же строку (не дублирует)
- `test_scores_are_rounded_to_2_decimals` — все оценки округлены до 2 знаков после запятой

#### `TestBuildRankedFeed`
- `test_empty_db_returns_empty_list` — пустая БД → пустой список
- `test_excludes_viewer_own_profile` — свой профиль не попадает в ленту
- `test_returns_other_profiles` — все чужие зарегистрированные профили присутствуют
- `test_excludes_already_swiped_profiles` — уже свайпнутые профили не показываются снова
- `test_respects_limit_parameter` — возвращает не более `limit` профилей

---

## Файл `tests/test_cache.py`

Тестирует **FeedCache** с `fakeredis` — полным in-memory эмулятором Redis.

```python
@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis_async.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()
```

`decode_responses=True` — Redis возвращает строки, а не байты. Это соответствует
тому, как `get_redis()` в `cache.py` конфигурирует настоящий Redis-клиент.

### Классы тестов

#### `TestFeedCacheBasics`
- `test_fill_and_get_next_returns_first` — первый `get_next` возвращает первый элемент
- `test_get_next_is_fifo` — порядок FIFO (очередь): 100, 200, 300 в том же порядке
- `test_empty_cache_returns_none` — пустой кэш → `None`
- `test_size_after_fill` — `size()` отражает количество элементов
- `test_size_decrements_after_pop` — после `get_next` размер уменьшается на 1

#### `TestFeedCacheFillOverwrite`
- `test_fill_overwrites_previous_data` — повторный `fill` заменяет старые данные
- `test_fill_with_empty_list_clears_cache` — `fill([])` очищает кэш
- `test_clear_empties_cache` — `clear()` полностью удаляет список
- `test_clear_on_empty_cache_does_not_raise` — `clear()` на пустом кэше безопасен

#### `TestFeedCacheIsolation`
- `test_different_users_have_independent_caches` — данные пользователей изолированы
- `test_pop_from_one_user_does_not_affect_another` — pop у одного не влияет на другого

---

## Файл `tests/test_tasks.py`

Тестирует **Celery-задачи** двумя способами.

### Проверка регистрации задач

```python
def test_refresh_all_ratings_is_registered():
    from app.celery_app import celery_app
    assert "app.tasks.refresh_all_ratings" in celery_app.tasks
```

Celery хранит все зарегистрированные задачи в словаре `celery_app.tasks`. Если
задача не найдена — воркер не сможет её выполнить.

### Паттерн `_FakeSessionFactory`

Задачи `_async_*` внутри вызывают `_make_session_factory()`, которая создаёт
реальный PostgreSQL-движок. В тестах мы подменяем её через `unittest.mock.patch`:

```python
class _FakeSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self          # Вызов factory() возвращает self

    async def __aenter__(self):
        return self._session  # Вход в context manager → наша тестовая сессия

    async def __aexit__(self, *args):
        pass
```

Это позволяет протестировать всю бизнес-логику задачи (обновление рейтинга,
логирование при отсутствии профиля) без реального PostgreSQL.

### Классы тестов

#### `TestTaskRegistration`
- `test_refresh_all_ratings_is_registered` — задача присутствует в реестре Celery
- `test_update_profile_rating_is_registered` — то же
- `test_beat_schedule_contains_refresh_all` — расписание Beat содержит периодическую задачу

#### `TestAsyncUpdateProfileRating`
- `test_updates_existing_profile_rating` — после вызова строка в `profile_ratings` обновлена
- `test_missing_profile_does_not_raise` — несуществующий `profile_id` → задача завершается без ошибки
- `test_engine_dispose_is_called` — `engine.dispose()` вызывается всегда (даже при ошибке)

#### `TestAsyncRefreshAllRatings`
- `test_empty_db_returns_zero` — нет профилей → возвращает 0
- `test_updates_all_profiles` — 3 профиля → возвращает 3, все записи в `profile_ratings` созданы
- `test_engine_dispose_called_after_all_ratings` — движок закрывается после пересчёта

---

## Конфигурация pytest

### `pytest.ini`
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`asyncio_mode = auto` — все `async def test_*` функции автоматически становятся
async-тестами без декоратора `@pytest.mark.asyncio`. Это настройка `pytest-asyncio`.

### `requirements-dev.txt`
```
pytest>=7.4.0
pytest-asyncio>=0.23.0
aiosqlite>=0.20.0
fakeredis>=2.20.0
ruff>=0.4.0
```

Отдельный файл от `requirements.txt`, чтобы production-окружение не тащило
тестовые зависимости.

---

## CI/CD через GitHub Actions

### Файл `.github/workflows/ci.yml`

GitHub Actions читает этот файл и запускает пайплайн автоматически.

### Триггеры запуска

```yaml
on:
  push:
    branches: ["**"]   # при любом push в любую ветку
  pull_request:
    branches: [main]   # при открытии PR в main
```

### Job 1: Lint

```yaml
lint:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4       # скачать код из репозитория
    - uses: actions/setup-python@v5   # установить Python 3.12
    - run: pip install ruff
    - run: ruff check app/ tests/ --select E,F,W --ignore E501
```

`ruff` — быстрый линтер (замена flake8). Проверяет:
- **E** — стилевые ошибки (PEP 8)
- **F** — реальные ошибки (undefined names, unused imports)
- **W** — предупреждения

`--ignore E501` — игнорируем длину строк (у нас длинные URL и строки в тестах).

### Job 2: Tests

```yaml
test:
  needs: lint           # запускается только если lint прошёл
  runs-on: ubuntu-latest
  steps:
    - pip install -r requirements.txt
    - pip install -r requirements-dev.txt
    - pytest tests/ -v --tb=short
```

`needs: lint` — тесты запускаются только если линтинг прошёл успешно. Это
экономит GitHub Actions минуты: если есть очевидные синтаксические ошибки,
тесты не запускаются.

**Почему не нужен PostgreSQL или Redis в CI?**
- Тесты используют SQLite in-memory (`aiosqlite`) вместо PostgreSQL
- Тесты используют `fakeredis` вместо настоящего Redis
- Оба работают внутри процесса Python без внешних зависимостей

### Job 3: Docker Build

```yaml
docker-build:
  needs: lint           # параллельно с tests, после lint
  steps:
    - docker build -t dating-bot:ci-${{ github.sha }} .
    - docker run --rm -e BOT_TOKEN=test_token dating-bot:... python -c "import app.bot"
```

Проверяет что:
1. `Dockerfile` корректен и все зависимости устанавливаются (`docker build`)
2. Образ запускается и Python-импорты работают (`docker run ... python -c "import app.bot"`)

`${{ github.sha }}` — уникальный хэш коммита, тег образа содержит его для
идентификации.

### Диаграмма пайплайна

```
git push
    │
    ▼
GitHub Actions
    │
    ├─── Job: lint ──────────────────────────────────► ✅/❌
    │         │
    │         ├─── (success) ──► Job: test ──────────► ✅/❌
    │         │
    │         └─── (success) ──► Job: docker-build ──► ✅/❌
    │
    └─── Все jobs пройдены → коммит получает зелёный статус ✅
```

### Почему два job'а после lint работают параллельно?

Оба `test` и `docker-build` имеют `needs: lint`. GitHub Actions запускает их
**одновременно** после того, как lint успешно завершился. Это сокращает общее
время пайплайна.

---

## Запуск тестов локально

```bash
# Установить dev-зависимости
pip install -r requirements-dev.txt

# Запустить все тесты
pytest tests/ -v

# Запустить конкретный файл
pytest tests/test_repository.py -v

# Запустить конкретный класс
pytest tests/test_ranking.py::TestBehaviorScore -v

# Запустить с подробным выводом при ошибке
pytest tests/ --tb=long
```

---

## Ответы на типовые вопросы преподавателя

**Q: Почему SQLite, а не PostgreSQL для тестов?**  
A: SQLite не требует запущенного сервера — тесты работают в любом окружении
(локально, в CI, на разных машинах). SQLAlchemy абстрагирует разницу между
диалектами: одни и те же ORM-запросы работают одинаково на SQLite и PostgreSQL.
Для юнит-тестов бизнес-логики это полностью достаточно.

**Q: Зачем `StaticPool` в тестовом движке?**  
A: SQLite in-memory хранит данные только внутри одного соединения. Если
SQLAlchemy откроет второе соединение (например, при создании новой сессии), оно
получит пустую БД. `StaticPool` принудительно переиспользует одно и то же
соединение для всего теста.

**Q: Почему `fakeredis` вместо мока?**  
A: С `unittest.mock` пришлось бы мокировать каждый метод Redis (`lpop`, `rpush`,
`expire`, `llen`, `delete`) и отслеживать state вручную. `fakeredis` реализует
полное Redis API в памяти — код `FeedCache` не знает, что работает не с настоящим
Redis. Это более надёжная проверка.

**Q: Зачем `_FakeSessionFactory` в `test_tasks.py`?**  
A: Celery-задачи создают свой движок SQLAlchemy через `_make_session_factory()`,
потому что им нужен движок внутри `asyncio.run()`. Мы подменяем эту функцию
через `patch`, передавая тестовую сессию (SQLite). Это позволяет тестировать всю
логику задачи, не поднимая PostgreSQL.

**Q: Что произойдёт если push упал на job `lint`?**  
A: Jobs `test` и `docker-build` не запустятся (оба имеют `needs: lint`). В
GitHub PR появится красный значок. Коммит не будет считаться «зелёным» до
исправления ошибок линтинга.

**Q: Как добавить новый тест?**  
A: Создать функцию `async def test_*` в нужном файле (или новом файле
`tests/test_*.py`). При `asyncio_mode = auto` она автоматически станет
async-тестом. При следующем `git push` CI запустит её вместе со всеми
остальными тестами.
