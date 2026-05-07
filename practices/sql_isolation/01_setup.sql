-- ============================================================
-- SETUP: Создание таблиц и тестовых данных
-- ============================================================
-- Запустите этот файл ОДИН РАЗ перед любой демонстрацией:
--   psql -U postgres -d postgres -f 01_setup.sql
-- ============================================================

DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;

CREATE TABLE accounts (
    id      SERIAL         PRIMARY KEY,
    name    VARCHAR(100)   NOT NULL,
    balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00
);

CREATE TABLE products (
    id       SERIAL         PRIMARY KEY,
    name     VARCHAR(100)   NOT NULL,
    price    NUMERIC(10, 2) NOT NULL,
    category VARCHAR(50)    NOT NULL
);

INSERT INTO accounts (name, balance) VALUES
    ('Alice',    1000.00),
    ('Bob',       500.00),
    ('Charlie',  2000.00);

INSERT INTO products (name, price, category) VALUES
    ('Laptop',   45000.00, 'Electronics'),
    ('Mouse',      800.00, 'Electronics'),
    ('Monitor',  15000.00, 'Electronics'),
    ('Desk',     12000.00, 'Furniture');

SELECT * FROM accounts ORDER BY id;
SELECT * FROM products ORDER BY id;
