-- Transaction SQL Scripts for Online Store

-- ==========================================
-- Сценарий 1: Размещение заказа
-- ==========================================
-- Параметры: CustomerID=1, ProductID=1 (Quantity=2), ProductID=2 (Quantity=1)
BEGIN TRANSACTION;

-- 1. Создаём новый заказ
INSERT INTO Orders (CustomerID, OrderDate, TotalAmount)
VALUES (1, datetime('now'), 0);

-- Получаем ID только что созданного заказа
-- В SQLite используем last_insert_rowid()

-- 2. Добавляем позиции заказа
-- Позиция 1: ProductID=1, Quantity=2, Price=29.99 -> Subtotal=59.98
INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal)
VALUES (last_insert_rowid(), 1, 2, 59.98);

-- Позиция 2: ProductID=2, Quantity=1, Price=49.99 -> Subtotal=49.99
INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal)
VALUES (last_insert_rowid(), 2, 1, 49.99);

-- 3. Обновляем общую сумму заказа на основе сумм промежуточных итогов
UPDATE Orders
SET TotalAmount = (
    SELECT SUM(Subtotal)
    FROM OrderItems
    WHERE OrderID = last_insert_rowid()
)
WHERE OrderID = last_insert_rowid();

COMMIT;


-- ==========================================
-- Сценарий 2: Обновление email клиента
-- ==========================================
-- Параметры: CustomerID=1, новый email='newemail@example.com'
BEGIN TRANSACTION;

-- Атомарное обновление email
UPDATE Customers
SET Email = 'newemail@example.com'
WHERE CustomerID = 1;

-- Проверка, что обновление прошло успешно (опционально)
-- SELECT Email FROM Customers WHERE CustomerID = 1;

COMMIT;


-- ==========================================
-- Сценарий 3: Добавление нового продукта
-- ==========================================
-- Параметры: ProductName='Laptop', Price=999.99
BEGIN TRANSACTION;

-- Атомарное добавление нового продукта
INSERT INTO Products (ProductName, Price)
VALUES ('Laptop', 999.99);

COMMIT;
