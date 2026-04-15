import sqlite3
import os
from datetime import datetime


DB_PATH = os.environ.get("DB_PATH", "/app/data/store.db")


def get_connection():
    """Получение соединения с базой данных."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Инициализация базы данных из schema.sql."""
    conn = get_connection()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        conn.executescript(f.read())

    # Добавляем тестовые данные, если таблица пуста
    cursor = conn.execute("SELECT COUNT(*) FROM Customers")
    if cursor.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO Customers (FirstName, LastName, Email) VALUES (?, ?, ?)",
            [
                ("John", "Doe", "john.doe@example.com"),
                ("Jane", "Smith", "jane.smith@example.com"),
                ("Alice", "Johnson", "alice.j@example.com"),
            ],
        )

    cursor = conn.execute("SELECT COUNT(*) FROM Products")
    if cursor.fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO Products (ProductName, Price) VALUES (?, ?)",
            [
                ("Keyboard", 29.99),
                ("Mouse", 49.99),
                ("Monitor", 199.99),
                ("Headphones", 79.99),
            ],
        )

    conn.commit()
    conn.close()
    print("Database initialized successfully.")


def scenario1_place_order(customer_id, order_items):
    """
    Сценарий 1: Транзакция размещения заказа.

    Параметры:
        customer_id: ID клиента
        order_items: список кортежей (product_id, quantity)

    Возвращает:
        order_id: ID созданного заказа
    """
    print("Сценарий 1: Размещение заказа")

    conn = get_connection()
    try:
        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")

        # 1. Создаём новую запись о заказе
        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO Orders (CustomerID, OrderDate, TotalAmount) VALUES (?, ?, 0)",
            (customer_id, order_date),
        )
        order_id = cursor.lastrowid
        print(f"  Создан заказ ID: {order_id}")

        # 2. Добавляем позиции заказа
        total_amount = 0.0
        for product_id, quantity in order_items:
            # Получаем цену продукта
            cursor = conn.execute(
                "SELECT ProductName, Price FROM Products WHERE ProductID = ?",
                (product_id,),
            )
            result = cursor.fetchone()
            if result is None:
                raise ValueError(f"Продукт с ID {product_id} не найден")

            product_name, price = result
            subtotal = round(price * quantity, 2)
            total_amount += subtotal

            conn.execute(
                "INSERT INTO OrderItems (OrderID, ProductID, Quantity, Subtotal) "
                "VALUES (?, ?, ?, ?)",
                (order_id, product_id, quantity, subtotal),
            )
            print(f"  Добавлено: {product_name} x{quantity} = ${subtotal:.2f}")

        # 3. Обновляем общую сумму заказа
        conn.execute(
            "UPDATE Orders SET TotalAmount = ? WHERE OrderID = ?",
            (round(total_amount, 2), order_id),
        )
        print(f"  Общая сумма заказа: ${total_amount:.2f}")

        # Коммитим транзакцию
        conn.commit()
        print(f"  Заказ {order_id} успешно создан")
        return order_id

    except Exception as e:
        conn.rollback()
        print(f"  Ошибка при создании заказа: {e}")
        raise
    finally:
        conn.close()


def scenario2_update_email(customer_id, new_email):
    """
    Сценарий 2: Атомарное обновление email клиента.

    Параметры:
        customer_id: ID клиента
        new_email: новый email

    Возвращает:
        True если обновление прошло успешно
    """
    print("Сценарий 2: Обновление email клиента")

    conn = get_connection()
    try:
        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")

        # Получаем текущий email
        cursor = conn.execute(
            "SELECT FirstName, LastName, Email FROM Customers WHERE CustomerID = ?",
            (customer_id,),
        )
        result = cursor.fetchone()
        if result is None:
            raise ValueError(f"Клиент с ID {customer_id} не найден")

        first_name, last_name, old_email = result
        print(f"  Клиент: {first_name} {last_name}")
        print(f"  Старый email: {old_email}")

        # Атомарное обновление email
        conn.execute(
            "UPDATE Customers SET Email = ? WHERE CustomerID = ?",
            (new_email, customer_id),
        )

        # Коммитим транзакцию
        conn.commit()
        print(f"  Новый email: {new_email}")
        print(f"  Email клиента {customer_id} обновлён")
        return True

    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"  Ошибка: email уже существует ({e})")
        raise
    except Exception as e:
        conn.rollback()
        print(f"  Ошибка при обновлении email: {e}")
        raise
    finally:
        conn.close()


def scenario3_add_product(product_name, price):
    """
    Сценарий 3: Атомарное добавление нового продукта.

    Параметры:
        product_name: название продукта
        price: цена продукта

    Возвращает:
        product_id: ID добавленного продукта
    """
    print("Сценарий 3: Добавление нового продукта")

    conn = get_connection()
    try:
        # Начинаем транзакцию
        conn.execute("BEGIN TRANSACTION")

        # Атомарное добавление нового продукта
        cursor = conn.execute(
            "INSERT INTO Products (ProductName, Price) VALUES (?, ?)",
            (product_name, price),
        )
        product_id = cursor.lastrowid

        # Коммитим транзакцию
        conn.commit()
        print(f"  Продукт: {product_name}, цена: ${price:.2f}, ID: {product_id}")
        print(f"  Продукт '{product_name}' добавлен")
        return product_id

    except sqlite3.IntegrityError as e:
        conn.rollback()
        print(f"  Ошибка целостности данных: {e}")
        raise
    except Exception as e:
        conn.rollback()
        print(f"  Ошибка при добавлении продукта: {e}")
        raise
    finally:
        conn.close()


def print_all_data(conn):
    print("\nCustomers:")
    for row in conn.execute("SELECT * FROM Customers"):
        print(f"  {row}")

    print("\nProducts:")
    for row in conn.execute("SELECT * FROM Products"):
        print(f"  {row}")

    print("\nOrders:")
    for row in conn.execute("SELECT * FROM Orders"):
        print(f"  {row}")

    print("\nOrderItems:")
    for row in conn.execute("SELECT * FROM OrderItems"):
        print(f"  {row}")


def main():
    """Главная функция - выполнение всех сценариев."""
    # Создаём директорию для базы данных
    data_dir = os.path.dirname(DB_PATH)
    if data_dir and data_dir != ".":
        os.makedirs(data_dir, exist_ok=True)

    # Инициализация базы
    init_db()

    # Выполняем сценарий 1: Размещение заказа
    scenario1_place_order(
        customer_id=1,
        order_items=[
            (1, 2),  # 2 Keyboard
            (2, 1),  # 1 Mouse
        ],
    )

    # Выполняем сценарий 2: Обновление email
    scenario2_update_email(
        customer_id=1,
        new_email="john.updated@example.com",
    )

    # Выполняем сценарий 3: Добавление продукта
    scenario3_add_product(product_name="Webcam", price=59.99)

    # Выводим итоговые данные
    conn = get_connection()
    print_all_data(conn)
    conn.close()

    print("\nВсе транзакции выполнены.")


if __name__ == "__main__":
    main()
