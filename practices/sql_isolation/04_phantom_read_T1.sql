-- ============================================================
-- АНОМАЛИЯ: PHANTOM READ (Фантомное чтение)
-- ТРАНЗАКЦИЯ T1 — выполняется в Терминале 1
-- ============================================================
--
-- ПОРЯДОК ВЫПОЛНЕНИЯ:
--   [T1-1] Выполните блок "[T1-1]" -> T1 считает строки (3 штуки)
--   [T2-1] Переключитесь на Терминал 2, выполните [T2-1]
--   [T1-2] Вернитесь, выполните [T1-2] -> T1 считает строки СНОВА
--
-- ТЕОРИЯ: Phantom read — в рамках одной транзакции T1 дважды
-- выполняет запрос с условием (WHERE) и получает разные НАБОРЫ
-- строк, потому что T2 добавила строку между двумя чтениями.
-- В отличие от non-repeatable read: здесь меняется количество
-- строк (появляются "фантомы"), а не значение в одной строке.
--
-- Уровень изоляции, при котором воспроизводится: READ COMMITTED
-- Предотвращается на уровне: SERIALIZABLE
-- (REPEATABLE READ в PostgreSQL тоже предотвращает phantom read!)
-- ============================================================

-- ===================== [T1-1] =====================

BEGIN;
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;

SELECT COUNT(*) AS count_electronics
FROM products
WHERE category = 'Electronics';

SELECT id, name, price, category
FROM products
WHERE category = 'Electronics'
ORDER BY id;

-- ===================== [T1-2] =====================
-- Выполните ПОСЛЕ того как T2 закоммитила вставку

SELECT COUNT(*) AS count_electronics
FROM products
WHERE category = 'Electronics';

SELECT id, name, price, category
FROM products
WHERE category = 'Electronics'
ORDER BY id;

COMMIT;
