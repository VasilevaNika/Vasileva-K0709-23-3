# Схема БД

СУБД: **PostgreSQL**. Создание таблиц: [03-database-schema.sql](03-database-schema.sql).

## Таблицы и связи

| Таблица | Назначение |
|---------|------------|
| `users` | Учётная запись: `telegram_id`, дата создания, активность. |
| `profiles` | Анкета: имя, био, дата рождения, пол, город, интересы, полнота заполнения. |
| `profile_photos` | Фото анкеты: ссылка на объект в S3 (`storage_key`), порядок сортировки. |
| `user_preferences` | Кого ищет пользователь: пол, возрастной диапазон, город. |
| `swipes` | Действия в ленте: лайк/пас; одна запись на пару (кто → кому). |
| `matches` | Взаимный лайк; пара пользователей хранится в каноническом порядке (`user_a_id < user_b_id`). |
| `messages` | Сообщения в чате мэтча. |
| `profile_ratings` | Кэш оценок: первичный, поведенческий, комбинированный скор; время обновления. |

Связи: один пользователь — одна анкета и одни предпочтения; у анкеты много фото; у мэтча много сообщений; у профиля — одна строка рейтинга (при необходимости расширения — версионирование или история в отдельной таблице).

## ER-диаграмма

```mermaid
erDiagram
  users ||--o| profiles : has
  users ||--o| user_preferences : has
  profiles ||--o{ profile_photos : contains
  users ||--o{ swipes : sends
  users ||--o{ matches : participates
  matches ||--o{ messages : has
  profiles ||--o| profile_ratings : scored

  users {
    bigint id PK
    bigint telegram_id UK
    timestamp created_at
    boolean is_active
  }

  profiles {
    bigint id PK
    bigint user_id FK
    string display_name
    text bio
    date birth_date
    string gender
    string city
    text interests
    int profile_completeness
  }

  profile_photos {
    bigint id PK
    bigint profile_id FK
    string storage_key
    int sort_order
  }

  user_preferences {
    bigint user_id PK
    string preferred_gender
    int age_min
    int age_max
    string preferred_city
  }

  swipes {
    bigint id PK
    bigint from_user_id FK
    bigint to_user_id FK
    string action
    timestamp created_at
  }

  matches {
    bigint id PK
    bigint user_a_id FK
    bigint user_b_id FK
    timestamp created_at
  }

  messages {
    bigint id PK
    bigint match_id FK
    bigint sender_id FK
    text body
    timestamp sent_at
  }

  profile_ratings {
    bigint profile_id PK
    float primary_score
    float behavior_score
    float combined_score
    timestamp updated_at
  }
```

## Рейтинг и таблицы

| Уровень рейтинга | Источники в БД |
|------------------|----------------|
| Первичный | `profiles`, `profile_photos`, `user_preferences` (и фильтры «кого показываем»). |
| Поведенческий | `swipes`, `matches`, `messages` (время — по `created_at` / `sent_at`). |
| Комбинированный | Агрегаты в `profile_ratings`; рефералы — при внедрении отдельная таблица `referrals`. |

## Индексы (см. также DDL)

В SQL-файле заданы индексы под типичные запросы: свайпы по получателю, сообщения по мэтчу, поиск пользователя по `telegram_id`.
