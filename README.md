# Carwash Booking API

Бекенд вебсервісу для запису на автомийку та детейлінг. Це серверна частина, яку я роблю в межах лабораторних робіт з вебпрограмування, а потім використаю в курсовій і кваліфікаційній роботах.

## Що вміє (лабораторна 1)

- каталог послуг, пости, автомобілі клієнтів, користувачі з ролями (клієнт / майстер / адміністратор);
- запис на **кілька послуг одним візитом** (зв'язок M:N), тривалість і вартість рахуються автоматично;
- автоматичний підбір вільного поста й захист від подвійного бронювання;
- пошук вільних слотів на дату;
- статуси запису з контролем дозволених переходів;
- пагінація, пошук і фільтри у списках, єдиний формат помилок, авто-документація API.

Автентифікація, JWT і розмежування доступу — у лабораторній 2, сповіщення в реальному часі — у лабораторній 3.

## Стек

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · Pydantic 2 · Argon2id (argon2-cffi) · pytest

> Методичка написана під Node.js + Express + Prisma, тому я використовую Python-відповідники: FastAPI замість Express, SQLAlchemy + Alembic замість Prisma, Pydantic замість ручної валідації.

## Запуск

```bash
git clone <посилання на репозиторій>
cd carwash-booking-api

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # за потреби підправити значення
docker compose up -d             # PostgreSQL на порту 5433

alembic upgrade head             # створити таблиці
python -m scripts.seed           # адмін, 3 пости, 14 послуг (необов'язково)

uvicorn app.main:app --reload
```

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Перевірка стану: http://localhost:8000/health

Перша міграція, якщо таблиць ще немає: `alembic revision --autogenerate -m "init schema"`, потім `alembic upgrade head`.

## Тести

```bash
pytest
```

Тести працюють на SQLite в пам'яті, Docker для них не потрібен.

## Основні ендпоїнти

Усі, крім `/health`, мають префікс `/api`. Повний перелік зі схемами — у Swagger.

| Ресурс | Методи |
|---|---|
| `/users` | `POST`, `GET` (пошук, `role`, `is_active`), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` |
| `/cars` | `POST`, `GET` (`owner_id`, `search`), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` |
| `/services` | `POST`, `GET` (`search`, `category`, `is_active`), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` |
| `/bays` | `POST`, `GET`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` |
| `/bookings` | `POST`, `GET` (`status`, `client_id`, `car_id`, `bay_id`, `master_id`, `date_from`, `date_to`) |
| `/bookings/availability` | `GET ?date=РРРР-ММ-ДД&service_ids=1&service_ids=2` — вільні слоти |
| `/bookings/{id}` | `GET`, `PATCH` (призначити майстра), `DELETE` (лише скасований) |
| `/bookings/{id}/status` | `PATCH` — зміна статусу |

Списки віддають `{ items, total, page, limit, pages }`, параметри `page` та `limit` (до 100).

## Формат помилок

```json
{ "error": "Обраний пост у цей час уже зайнятий" }
```

Помилки валідації (422) додатково мають `details` зі списком полів. Коди: 404 — не знайдено, 409 — конфлікт (дублікат, зайнятий слот, недозволений перехід статусу), 422 — порушено правило (минулий час, не робочі години, чужий автомобіль).

## Правила запису

- час передається **з часовим поясом** (`2026-10-25T10:00:00+03:00`);
- запис має повністю вміщатися в робочий день (за замовчуванням 9:00–20:00, змінюється в `.env`);
- пост обирається автоматично або вказується явно; перетин за часом на одному посту неможливий;
- ціна й тривалість послуг фіксуються в записі на момент створення;
- статуси: `planned → in_progress → done`, скасувати можна з `planned` та `in_progress`.

## Структура

```
app/
├── main.py            # створення застосунку, CORS, підключення роутерів
├── deps.py            # залежності: сесія БД, пагінація
├── core/              # config, database, errors, pagination, security
├── models/            # таблиці SQLAlchemy
├── schemas/           # Pydantic-схеми запитів і відповідей
├── routers/           # HTTP-маршрути
└── services/          # бізнес-логіка запису (booking_service.py)
alembic/               # міграції
scripts/seed.py        # початкові дані
tests/                 # pytest
```
