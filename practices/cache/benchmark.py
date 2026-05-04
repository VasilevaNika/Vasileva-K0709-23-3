from __future__ import annotations
import random
import time

from database import Database
from strategies import LazyCacheStrategy, WriteThroughStrategy, WriteBackStrategy

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

N_ITEMS = 100       # количество записей в БД
N_OPS   = 2000      # операций на один прогон
SEED    = 42        # для воспроизводимости

SCENARIOS: list[tuple[str, float]] = [
    ("read-heavy  (80% R / 20% W)", 0.80),
    ("balanced    (50% R / 50% W)", 0.50),
    ("write-heavy (20% R / 80% W)", 0.20),
]

LINE = "=" * 76


# ---------------------------------------------------------------------------
# Запуск одного прогона
# ---------------------------------------------------------------------------

def run_benchmark(strategy, read_ratio: float) -> dict:
    strategy.reset_metrics()

    rng = random.Random(SEED)
    keys = list(range(N_ITEMS))

    n_reads  = int(N_OPS * read_ratio)
    ops      = ["R"] * n_reads + ["W"] * (N_OPS - n_reads)
    rng.shuffle(ops)

    t_start = time.perf_counter()
    for op in ops:
        key = rng.choice(keys)
        if op == "R":
            strategy.read(key)
        else:
            strategy.write(key, f"v{key}_{rng.randint(0, 9999)}")
    elapsed = time.perf_counter() - t_start

    # Для Write-Back — сбрасываем всё что успело накопиться
    if isinstance(strategy, WriteBackStrategy):
        strategy.force_flush()

    return {
        "throughput":      N_OPS / elapsed,
        "avg_latency_ms":  elapsed / N_OPS * 1000,
        "db_accesses":     strategy.db.access_count,
        "hit_rate_pct":    strategy.hit_rate() * 100,
    }


# ---------------------------------------------------------------------------
# Write-Back: демонстрация накопления записей
# ---------------------------------------------------------------------------

def demo_writeback_accumulation(db: Database) -> None:
    THRESHOLD = 30

    print(f"\n{LINE}")
    print("  WRITE-BACK: Демонстрация накопления грязных записей")
    print(f"  flush_threshold={THRESHOLD}, flush_interval=∞ (ручной flush)")
    print(LINE)

    # Создаём отдельный экземпляр с очень большим интервалом —
    # фоновый поток не будет мешать демонстрации
    wb = WriteBackStrategy(db, flush_interval=9999.0, flush_threshold=THRESHOLD)
    db.reset_counter()

    checkpoints = {10, 20, 29, 30, 31, 40, 50, 60, 61, 70}

    print(f"\n  {'Записей':>8}  {'Dirty-буфер':>13}  {'Обращ. в БД':>13}  Событие")
    print(f"  {'-'*8}  {'-'*13}  {'-'*13}  {'-'*30}")

    for i in range(1, 71):
        wb.write(i % N_ITEMS, f"dirty_{i}")
        if i in checkpoints:
            note = ""
            if i == THRESHOLD:
                note = "<<< threshold flush #1!"
            elif i == THRESHOLD * 2:
                note = "<<< threshold flush #2!"
            elif i == THRESHOLD + 1:
                note = "(буфер начат заново)"
            print(
                f"  {i:>8}"
                f"  {wb.dirty_count():>13}"
                f"  {db.access_count:>13}"
                f"  {note}"
            )

    remaining = wb.dirty_count()
    print(f"\n  В dirty-буфере осталось: {remaining} записей → вызываем force_flush()")
    wb.force_flush()
    print(f"  После force_flush: dirty={wb.dirty_count()}, db_accesses={db.access_count}")
    print(f"\n  Итого flush-операций: {wb.flush_count}  (вместо {70} отдельных записей в БД)")
    print(f"  Экономия обращений: {70 - db.access_count} из {70} ({(1 - db.access_count/70)*100:.0f}%)")
    wb.stop()


# ---------------------------------------------------------------------------
# Вывод таблицы
# ---------------------------------------------------------------------------

HEADER = (
    f"\n  {'Стратегия':<14}"
    f" {'Throughput':>14}"
    f" {'Avg Latency':>14}"
    f" {'DB Accesses':>13}"
    f" {'Hit Rate':>10}"
)
SEP = (
    f"  {'-'*14}"
    f" {'-'*14}"
    f" {'-'*14}"
    f" {'-'*13}"
    f" {'-'*10}"
)


def print_row(name: str, r: dict) -> None:
    print(
        f"  {name:<14}"
        f" {r['throughput']:>12,.0f}/s"
        f" {r['avg_latency_ms']:>12.4f} ms"
        f" {r['db_accesses']:>13,}"
        f" {r['hit_rate_pct']:>9.1f}%"
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    db = Database()
    db.seed(N_ITEMS)
    print(f"\n  БД заполнена: {N_ITEMS} записей (id 0..{N_ITEMS-1})")

    wb_strategy = WriteBackStrategy(db, flush_interval=0.5, flush_threshold=50)

    strategies: dict[str, object] = {
        "LazyLoading ": LazyCacheStrategy(db),
        "WriteThrough": WriteThroughStrategy(db),
        "WriteBack   ": wb_strategy,
    }

    print(f"\n{LINE}")
    print("  CACHE STRATEGY BENCHMARK")
    print(LINE)
    print(f"  Записей в БД: {N_ITEMS}  |  Операций/прогон: {N_OPS}  |  Seed: {SEED}")

    for scenario_name, read_ratio in SCENARIOS:
        print(f"\n{LINE}")
        print(f"  Сценарий: {scenario_name}")
        print(HEADER)
        print(SEP)
        for name, strategy in strategies.items():
            r = run_benchmark(strategy, read_ratio)
            print_row(name, r)

    # Останавливаем фоновый поток основного WriteBack до демонстрации
    wb_strategy.stop()

    # Демо накопления Write-Back
    demo_writeback_accumulation(db)

    print(f"\n{LINE}")
    print("  Benchmark завершён.")
    print(f"{LINE}\n")


if __name__ == "__main__":
    main()
