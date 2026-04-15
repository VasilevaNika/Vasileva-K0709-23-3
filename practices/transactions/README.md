# Online Store Transactions

Практическое задание: реализация SQL-транзакций для интернет-магазина.

## Структура проекта

- `schema.sql` — схема базы данных (Customers, Products, Orders, OrderItems)
- `transactions.sql` — SQL-скрипты с транзакциями для 3 сценариев
- `main.py` — Python-скрипт, реализующий те же сценарии программно
- `Dockerfile` — контейнер для приложения
- `docker-compose.yml` — запуск приложения и PostgreSQL

## Сценарии

### Сценарий 1: Размещение заказа
Транзакция создаёт запись в `Orders`, добавляет позиции в `OrderItems` и обновляет `TotalAmount`.

### Сценарий 2: Обновление email клиента
Атомарное обновление email в таблице `Customers`.

### Сценарий 3: Добавление нового продукта
Атомарное добавление продукта в таблицу `Products`.

## Запуск

```bash
# Локально
DB_PATH=./data/store.db python3 main.py

# Через Docker Compose
docker-compose up --build
```
