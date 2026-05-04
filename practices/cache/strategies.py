from __future__ import annotations
import threading
import fakeredis

from database import Database


# ---------------------------------------------------------------------------
# Base class — общий кеш (fakeredis), счётчики hits/misses
# ---------------------------------------------------------------------------

class _Base:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.cache = fakeredis.FakeRedis()
        self._hits = 0
        self._misses = 0

    def reset_metrics(self) -> None:
        """Сбрасывает все счётчики и очищает кеш перед каждым прогоном."""
        self._hits = 0
        self._misses = 0
        self.cache.flushall()
        self.db.reset_counter()

    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total else 0.0

    # -- внутренние хелперы ------------------------------------------------

    def _cache_get(self, key: int) -> str | None:
        raw = self.cache.get(f"k:{key}")
        if raw is not None:
            self._hits += 1
            return raw.decode()
        self._misses += 1
        return None

    def _cache_set(self, key: int, value: str) -> None:
        self.cache.set(f"k:{key}", value)


# ---------------------------------------------------------------------------
# 1. Cache-Aside  (Lazy Loading / Write-Around)
# ---------------------------------------------------------------------------

class LazyCacheStrategy(_Base):
    """
    Чтение:  cache miss → читаем БД → кладём в кеш.
    Запись:  идёт напрямую в БД; запись в кеш НЕ обновляется (только инвалидация).
    """

    def read(self, key: int) -> str | None:
        value = self._cache_get(key)
        if value is None:                       # cache miss
            value = self.db.read(key)
            if value is not None:
                self._cache_set(key, value)     # lazy populate
        return value

    def write(self, key: int, value: str) -> None:
        self.db.write(key, value)               # сразу в БД
        self.cache.delete(f"k:{key}")           # инвалидируем устаревший кеш


# ---------------------------------------------------------------------------
# 2. Write-Through
# ---------------------------------------------------------------------------

class WriteThroughStrategy(_Base):
    """
    Чтение:  аналогично Cache-Aside.
    Запись:  одновременно в БД И в кеш → кеш всегда актуален.
    """

    def read(self, key: int) -> str | None:
        value = self._cache_get(key)
        if value is None:
            value = self.db.read(key)
            if value is not None:
                self._cache_set(key, value)
        return value

    def write(self, key: int, value: str) -> None:
        self.db.write(key, value)               # в БД
        self._cache_set(key, value)             # сразу и в кеш


# ---------------------------------------------------------------------------
# 3. Write-Back  (Write-Behind)
# ---------------------------------------------------------------------------

class WriteBackStrategy(_Base):
    """
    Чтение:  аналогично Cache-Aside.
    Запись:  сначала только в кеш; «грязные» ключи копятся в dirty-буфере.
    Flush:   либо когда буфер заполняется до flush_threshold,
             либо через flush_interval секунд (фоновый поток).
    """

    def __init__(
        self,
        db: Database,
        flush_interval: float = 1.0,
        flush_threshold: int = 20,
    ) -> None:
        super().__init__(db)
        self.flush_interval = flush_interval
        self.flush_threshold = flush_threshold
        self.flush_count: int = 0

        self._dirty: dict[int, str] = {}
        self._dirty_lock = threading.Lock()

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._bg_flush, daemon=True)
        self._thread.start()

    # -- public API --------------------------------------------------------

    def reset_metrics(self) -> None:
        super().reset_metrics()
        with self._dirty_lock:
            self._dirty.clear()
        self.flush_count = 0

    def dirty_count(self) -> int:
        with self._dirty_lock:
            return len(self._dirty)

    def read(self, key: int) -> str | None:
        value = self._cache_get(key)
        if value is None:
            value = self.db.read(key)
            if value is not None:
                self._cache_set(key, value)
        return value

    def write(self, key: int, value: str) -> None:
        self._cache_set(key, value)             # быстрая запись в кеш

        snapshot = None
        with self._dirty_lock:
            self._dirty[key] = value
            if len(self._dirty) >= self.flush_threshold:
                snapshot = list(self._dirty.items())
                self._dirty.clear()

        if snapshot:                            # flush вне лока (I/O без блокировки)
            self.db.write_batch(snapshot)
            self.flush_count += 1

    def force_flush(self) -> None:
        """Немедленно сбрасывает все грязные записи в БД."""
        snapshot = None
        with self._dirty_lock:
            if self._dirty:
                snapshot = list(self._dirty.items())
                self._dirty.clear()
        if snapshot:
            self.db.write_batch(snapshot)
            self.flush_count += 1

    def stop(self) -> None:
        """Останавливает фоновый поток и делает финальный flush."""
        self._stop.set()
        self.force_flush()

    # -- internal ----------------------------------------------------------

    def _bg_flush(self) -> None:
        while not self._stop.wait(self.flush_interval):
            self.force_flush()
