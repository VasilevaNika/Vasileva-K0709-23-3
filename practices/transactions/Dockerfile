FROM python:3.11-slim

WORKDIR /app

# Копируем файлы приложения
COPY schema.sql transactions.sql main.py ./

# Создаём директорию для данных
RUN mkdir -p /app/data

# Запускаем приложение
CMD ["python", "main.py"]
