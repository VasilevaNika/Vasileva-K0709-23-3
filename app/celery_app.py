"""
Celery-приложение для фоновых задач Dating Bot.

Брокер и бэкенд результатов — Redis (тот же инстанс, что и для FeedCache,
но другие номера баз данных, чтобы данные не перемешивались):
  DB 0 — FeedCache (кэш ленты анкет)
  DB 1 — Celery broker (очередь задач)
  DB 2 — Celery result backend (результаты выполненных задач)

Запуск воркера:
    celery -A app.celery_app worker --loglevel=info

Запуск планировщика периодических задач (Beat):
    celery -A app.celery_app beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "dating_bot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks"],
)

celery_app.conf.update(
    # Сериализация
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Временная зона
    timezone="UTC",
    enable_utc=True,
    # Результаты задач хранить 1 час, потом автоматически удаляются
    result_expires=3600,
    # Повтор задачи при потере соединения с брокером
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# ─── Расписание периодических задач (Celery Beat) ─────────────────────────────

celery_app.conf.beat_schedule = {
    # Каждые 10 минут пересчитываем рейтинги всех профилей
    "refresh-all-ratings-every-10-min": {
        "task": "app.tasks.refresh_all_ratings",
        "schedule": crontab(minute="*/10"),
    },
}
