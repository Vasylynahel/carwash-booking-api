# WebSocket API (Socket.IO)

Реальний час реалізовано на **python-socketio** (Socket.IO 4). Клієнту потрібна бібліотека `socket.io-client`, а не вбудований `WebSocket` браузера: Socket.IO має власний протокол поверх WebSocket.

- Адреса: корінь сервера, **без** `/api` (наприклад, `http://localhost:8000`). Шлях `/socket.io`.
- Запуск сервера: `uvicorn app.main:application` (не `app.main:app`: `application` обгортає FastAPI та Socket.IO).
- Демо без фронтенду: відкрийте `http://localhost:8000/demo` у двох вікнах.

## Автентифікація

Токен доступу (JWT з `/api/auth/login`) передається під час підключення в `auth.token`:

```js
import { io } from "socket.io-client";

const socket = io("http://localhost:8000", {
  // функція: при кожному (пере)підключенні береться актуальний токен
  auth: (cb) => cb({ token: useAuthStore.getState().accessToken }),
});
socket.on("connect_error", (e) => console.log(e.message)); // "unauthorized"
```

Без токена, з недійсним токеном чи refresh-токеном сервер відхиляє з'єднання (`connect_error: unauthorized`). Перевіряється також `Origin`: допускаються лише адреси з `FRONTEND_URL` та `EXTRA_CORS_ORIGINS`.

**Токен спливає під час відкритого з'єднання.** Сервер перевіряє термін при кожній вхідній події. Якщо токен прострочено, клієнт отримує подію `auth:expired`, а з'єднання закривається. Клієнт оновлює токен через `POST /api/auth/refresh` і підключається знову з новим `auth.token`.

## Формат подій від сервера

Усі події мають однакову обгортку:

```json
{ "id": 1234, "data": { ... } }
```

`id` — номер у журналі подій (див. «Відновлення»), для подій без журналу `null`.

## Кімнати

Після підключення користувач автоматично потрапляє в кімнати:

| Кімната | Хто | Що отримує |
|---|---|---|
| `user:{id}` | кожен | персональні події й сповіщення |
| `role:{client\|master\|admin}` | за роллю | адміністратори отримують усі події записів і онлайн-статуси |
| `all` | кожен | зміни каталогу |
| `slots:{РРРР-ММ-ДД}` | за підпискою | зміни вільних слотів на дату |

## Події від сервера

| Подія | Кому | Дані (`data`) | У журналі |
|---|---|---|---|
| `booking:created` | клієнт запису, його майстер, адміни | `id, status, client_id, car_id, bay_id, master_id, scheduled_at, ends_at, total_price, discount_percent` | так |
| `booking:updated` | те саме (призначено майстра) | те саме | так |
| `booking:status` | те саме (змінено статус) | те саме | так |
| `booking:deleted` | те саме | те саме | так |
| `notification` | власник сповіщення | `id, type, priority, message, booking_id, is_read, created_at` | ні (є в БД) |
| `slots:changed` | підписники дати | `date` | ні |
| `catalog:changed` | усі | `entity (service\|bay\|pricing_rule), id, action (created\|updated\|deleted\|auto_applied)` | ні |
| `presence:update` | адміни | `user_id, role, online` | ні |
| `auth:expired` | з'єднання | `{}` | ні |

Типи сповіщень (`type`): `booking_created`, `booking_status`, `booking_cancelled`, `master_assigned`. Пріоритети: `low`, `normal`, `high` (наприклад, скасування адміністратором і призначення майстра мають `high`).

## Події від клієнта

Усі відповідають через **acknowledgement** (останній аргумент-колбек). Помилка має вигляд `{ "ok": false, "code": "..." }`.

| Подія | Дані | Відповідь |
|---|---|---|
| `events:since` | `{ "last_id": 123 }` | `{ ok, events: [{id, type, room, data, created_at}], has_more }` |
| `slots:subscribe` | `{ "date": "2026-11-01" }` | `{ ok, date }` або `BAD_DATE`, `TOO_MANY_SUBSCRIPTIONS` (максимум 10 дат) |
| `slots:unsubscribe` | `{ "date": "2026-11-01" }` | `{ ok }` |
| `presence:list` | `{}` | `{ ok, users: [{user_id, role, name, connections}] }` лише для адміна, інакше `FORBIDDEN` |

Коди помилок: `TOKEN_EXPIRED`, `RATE_LIMITED` (більше 30 подій за 10 с від одного з'єднання; значення в `.env`), `BAD_REQUEST`, `BAD_DATE`, `FORBIDDEN`.

## Відновлення після втрати з'єднання

Socket.IO сам перепідключається, але події, що відбулись поки клієнт був офлайн, втрачаються. Тому важливі події (`booking:*`) ще й записуються в таблицю `events` з наскрізним номером.

```js
let lastId = 0;
for (const ev of ["booking:created", "booking:updated", "booking:status", "booking:deleted"]) {
  socket.on(ev, (p) => { lastId = Math.max(lastId, p.id); /* оновити інтерфейс */ });
}
socket.on("connect", () => {
  socket.emit("events:since", { last_id: lastId }, (res) => {
    res.events.forEach((e) => { lastId = Math.max(lastId, e.id); /* застосувати e.type, e.data */ });
    // res.has_more === true: повторити запит із новим lastId
  });
  // слоти та сповіщення не мають журналу: просто перезавантажте їх
  // GET /api/notifications?is_read=false, GET /api/bookings/availability
});
```

Те саме без WebSocket: `GET /api/events?since=123`. Події зберігаються `EVENTS_RETENTION_DAYS` (7) днів, старіші чистить фонове завдання.

Що **не** відновлюється через журнал: `slots:changed`, `catalog:changed`, `presence:update`, `notification`. Після перепідключення їх замінюють запити REST: слоти й каталог перезапитуються, а сповіщення береться з `GET /api/notifications`.

## Масштабування

За замовчуванням стан з'єднань живе в пам'яті одного процесу. Щоб запустити кілька копій сервера, задайте `REDIS_URL`: розсилка подій тоді йде через Redis (pub/sub). Вимоги:

- балансувальник має мати «липкі сесії» (sticky sessions), або клієнти мають підключатися лише транспортом `websocket` (`transports: ["websocket"]`);
- онлайн-статус (`presence`) і ліміт подій зараз зберігаються в пам'яті процесу, тому за кількох копій вони показують лише з'єднання своєї копії. Для повного рішення їх теж потрібно перенести в Redis.

Підтримку Redis у цьому проєкті налаштовано, але на живому Redis вона не перевірялась.
