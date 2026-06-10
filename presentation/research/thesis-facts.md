# FACTS SHEET — VPN-застосунок з двофакторною автентифікацією на основі WireGuard

> Single source of truth for the 5-minute defense presentation. All numbers
> verbatim from the thesis. "not stated" = not present in the text.
> Thesis volume: **99 сторінок, 14 таблиць, 17 рисунків, 45 джерел, 1 додаток.**
> Keywords (Ключові слова): VPN, WireGuard, двофакторна автентифікація, TOTP,
> мережева безпека, захист даних, тунелювання трафіку.

---

## 1. ONE-SENTENCE THESIS (мета роботи)

**Мета роботи (verbatim, abstract):**
> «Розробка VPN-застосунку з двофакторною автентифікацією на основі протоколу
> WireGuard, що поєднує захищене тунелювання мережевого трафіку з надійним
> механізмом автентифікації користувача.»

(Introduction wording is shorter: «Метою дипломної роботи є розробка
VPN-застосунку з двофакторною автентифікацією на основі протоколу WireGuard.»)

**Об'єкт дослідження (object):** процес автентифікації користувачів у VPN-мережах.
*(the process of user authentication in VPN networks)*

**Предмет дослідження (subject):** методи інтеграції двофакторної автентифікації
з протоколом WireGuard. *(methods of integrating 2FA with the WireGuard protocol)*

**Завдання (tasks):** (1) проаналізувати технології VPN та методи 2FA; (2) дослідити
архітектуру та криптографічні основи WireGuard; (3) порівняти існуючі рішення
інтеграції автентифікації з WireGuard; (4) розробити архітектуру системи; (5)
реалізувати програмний комплекс, провести функціональне тестування та порівняльний
аналіз продуктивності щодо чистого WireGuard і OpenVPN.

---

## 2. THE PROBLEM — why WireGuard lacks user authentication

WireGuard ідентифікує вузли **виключно за статичними публічними ключами**
(Cryptokey Routing). Автентифікація пакетів відбувається **на рівні
криптографічних ключів, а не IP-адрес чи облікових даних**. Наслідки:

- відсутня перевірка особи (хто саме використовує ключ);
- відсутня підтримка двофакторної автентифікації;
- неможливе **динамічне відкликання доступу** без ручного видалення ключа з конфігурації сервера;
- відсутній журнал автентифікації (хто і коли підключився).

Це **свідоме архітектурне рішення**: WireGuard позиціонується як мінімальний
примітив **рівня даних (data plane)**; управління ідентичністю/доступом
навмисно винесено за межі протоколу (≈4 000 LOC, формально верифікований).

**Risk scenario (verbatim concept):** скомпрометований ноутбук, WireGuard-ключі
залишаються валідними — зловмисник зберігає доступ до тунелю, доки адміністратор
вручну не відредагує конфігурацію сервера. У середовищах під аудитом
(**SOC 2 CC6.1, ISO 27001 A.9.4.2**) самих лише криптографічних ключів
недостатньо для підтвердження ідентичності у момент під'єднання.

**Contrast with other protocols:** інші VPN-протоколи (**IPsec, OpenVPN**)
**інтегруються з EAP / RADIUS / LDAP**. WireGuard за специфікацією обмежується
перевіркою криптографічних ключів і не передбачає механізмів автентифікації
користувачів.

---

## 3. THE NOVELTY CLAIM (наукова новизна)

**Verbatim (abstract):**
> «Удосконалено підхід до інтеграції двофакторної автентифікації з протоколом
> WireGuard **без модифікації протоколу** та **без використання попередньо
> узгоджених ключів** (PSK).»

**Verbatim (introduction):**
> «На відміну від рішень типу **DefGuard**, запропонований підхід не потребує
> модифікації протоколу WireGuard та використання попередньо узгоджених ключів (PSK).»

**Plain restatement (EN):** The system adds mandatory 2FA on top of stock
WireGuard purely in the *control plane*. Sessions are gated by adding/removing
WireGuard peers — no protocol change, no PSK manipulation. Contrast with
DefGuard, which rotates the *preshared key (PSK)* as a session token and
therefore requires its own non-standard client.

**Academic gap noted:** у науковій літературі **відсутні рецензовані публікації**
щодо систематичного підходу до інтеграції 2FA з WireGuard — наявні лише практичні
реалізації у відкритому ПЗ.

---

## 4. ARCHITECTURE

### "Сесія як вузол" (session-as-node) model — 2-3 sentences
Вузол WireGuard (peer) з'являється на інтерфейсі `wg0` **виключно після
успішної двофакторної автентифікації** і **видаляється** у момент завершення
або відкликання сесії. Це забезпечує властивість **session-gated VPN access**:
WireGuard-з'єднання фізично неможливе без чинної автентифікованої сесії —
навіть володіючи клієнтським публічним ключем, без запису вузла на сервері
тунель не встановити. На відміну від DefGuard (PSK-токен), це
прямолінійне рішення: «вузол або є, або ні» (два subprocess-виклики).

### Загальна архітектура
**Монолітна** (не мікросервісна), причини: мінімальна складність розгортання
(`docker compose up`), прозорість для академічної оцінки, масштаб ~десятки
користувачів, локальне управління інтерфейсом `wg0`. Принцип **YAGNI**.

Дві Docker-контейнери: **caddy** (зворотний проксі, авто-TLS) і **vpn-server**
(монолітний застосунок: API + SQLite + інтерфейс `wg0`). Два канали клієнта:
HTTPS (управління) і UDP-тунель WireGuard (трафік).

### Декомпозиція на модулі (9 модулів, табл. «Модулі серверного застосунку»)
| Модуль | Відповідальність |
|---|---|
| `auth` | Реєстрація, перевірка пароля (Argon2id), видача JWT |
| `totp` | Генерація TOTP-секретів, зашифроване зберігання (Fernet), верифікація кодів |
| `sessions` (код: `vpn/`) | Повний життєвий цикл VPN-сесії: створення, перевірка, завершення, відкликання |
| `wireguard` | Управління `wg0`: додавання/видалення вузлів, статистика |
| `admin` | Адміністративний API (списки користувачів, керування сесіями) |
| `api` | FastAPI-маршрути, схеми запитів/відповідей (Pydantic) |
| `models` | SQLAlchemy ORM-моделі |
| `config` | Налаштування через змінні середовища (Pydantic Settings) |
| `tasks` | Фонові завдання: очищення прострочених сесій (кожні 60 с) |

Структура коду: `src/vpnservice/` (auth, totp, vpn, wireguard, admin, tasks,
main.py, models.py, config.py) + `src/vpncli/` (main.py, tunnel.py, auth.py,
api_client.py). Клієнт `vpncli` на Typer.

### TECH STACK (exact names/versions from text)
| Компонент | Технологія | Версія/деталі |
|---|---|---|
| Мова | Python 3 | async/await |
| HTTP-фреймворк | FastAPI | `fastapi >= 0.115` |
| ASGI-сервер | Uvicorn | на основі uvloop |
| ORM | SQLAlchemy 2.0 | `sqlalchemy[asyncio] >= 2.0`, типізований ORM; Alembic для міграцій |
| БД | SQLite (WAL mode) | драйвер `aiosqlite`; файл `vpnservice.db` |
| Зворотний проксі | Caddy 2 | офіційний образ `caddy:2`, авто-TLS Let's Encrypt (ACME) |
| Хешування паролів | Argon2id | бібліотека `argon2-cffi`; профіль RFC_9106_LOW_MEMORY (3 ітерації, 64 МіБ, паралелізм 4) |
| Токени | JWT (PyJWT, **HS256** / HMAC-SHA256) | stateless |
| Шифрування секретів | Fernet (`cryptography`) | AES-128-CBC + HMAC-SHA256 |
| TOTP | `pyotp` | RFC 6238, otpauth URI; QR через `qrcode` |
| CLI | Typer + `rich` + `httpx` (sync) | клієнт `vpncli` |
| Контейнеризація | Docker Compose | два контейнери |
| Тести | `pytest` + `pytest-asyncio` (`asyncio_mode="auto"`) | — |

WireGuard-операції — через системні утиліти `wg` та `ip` (пакети
`wireguard-tools`, `iproute2`) — **без сторонніх Python-бібліотек для WireGuard**.

---

## 5. AUTH FLOW — двоетапний вхід (two-step login)

**Реєстрація:** `POST /api/v1/auth/register` {username, password} → сервер
генерує TOTP-секрет, повертає `totp_secret`, `totp_uri` (otpauth://), QR
(base64 PNG), `auth_token`. Користувач **зобов'язаний** підтвердити один код
(`POST /auth/totp/verify`) — інакше `is_verified=false` у `totp_secrets`,
а спроба входу → **403 Forbidden**. Обхід 2FA на рівні API виключено.

**Двоетапний вхід (login):**
1. **Перевірка пароля** — `POST /api/v1/auth/login` {username, password}.
   Сервер перевіряє хеш **Argon2id**, повертає **проміжний токен**
   (**TTL: 5 хвилин, scope: `totp_verify`**). Дійсний виключно для ендпоінту верифікації TOTP.
2. **Верифікація TOTP** — `POST /api/v1/auth/totp/verify`, 6-значний код +
   проміжний токен у `Authorization`. Перевірка у вікні **±1 часовий крок (±30 с)**.
   Повертає **токен повного доступу** (**TTL: 24 години, scope: `full`**;
   для адмінів `is_admin: true`).

**Де що використовується:**
- **Argon2id** — хешування/перевірка пароля (крок 1). Бібліотека `argon2-cffi`,
  захисне порівняння з постійним часом виконання.
- **TOTP / RFC 6238** — другий фактор (крок 2). `T0=0`, `X=30 c`, вікно ±1 крок.
  Бібліотека `pyotp`.
- **JWT** — два токени, обидва підписані **HS256 (HMAC-SHA256)** одним секретом
  `VPN_JWT_SECRET`; різниця лише за claim `scope` (перевіряється у middleware).
  Stateless — у БД не зберігаються. (Стандарт: ключ ≥256 біт / 32 байти для HS256.)
- **Fernet** — шифрування TOTP-секрету *у стані спокою* в БД (не у flow логіну).
  Ключ виводиться з `VPN_SECRET_KEY` через **HKDF**, зберігається лише у env.

---

## 6. WIREGUARD INTEGRATION

**Sessions → wg0 peers:**
- **Додавання вузла:** `wg set wg0 peer <pubkey> allowed-ips <ip>/32` —
  синхронно під час `POST /api/v1/vpn/sessions`.
- **Видалення вузла:** `wg set wg0 peer <pubkey> remove` — при відкликанні
  через API або автоматично фоновим завданням при закінченні TTL.
- **Статистика:** `wg show wg0 dump` → `last_handshake`, `transfer_rx`, `transfer_tx`.
- Реалізація: клас `WireGuardManager`, виклики через `asyncio.create_subprocess_exec`
  (не блокують event loop). Деградований режим: якщо WireGuard недоступний,
  API працює, але запити на створення сесій → **503**.

**IP allocation:** підмережа за замовчуванням `10.10.0.0/24`; `10.10.0.1` —
сервер; пул клієнтів `10.10.0.2`–`10.10.0.254` (**253 адреси**). Алгоритм:
запит активних сесій з БД → вибір **найменшої вільної** адреси → атомарне
збереження при створенні сесії → повернення адреси у пул при `expired`/`revoked`.

**Background session cleanup (модуль `tasks`):** фонове завдання **кожні 60 секунд**.
Вибирає сесії `status=active` з `expires_at < now()`; для кожної — `wg set wg0
peer <pubkey> remove` + статус `expired` у БД. Запускається через
`asyncio.create_task` у `lifespan`; помилки циклу логуються, цикл триває.

**Data model — 5 сутностей:** `users` (UUIDv4 id, хеш Argon2id, `is_admin`,
`is_active`), `totp_secrets` (1:1 з users, секрет зашифрований Fernet, `is_verified`),
`devices` (унікальний WireGuard pubkey — 44 символи Base64; унікальність пари
user_id+name), `vpn_sessions` (`assigned_ip`, enum `status`: active/expired/revoked,
`expires_at` UTC), `system_settings` (singleton, CHECK(id=1); `max_sessions_per_user`,
`session_ttl_hours`).

---

## 7. EXISTING SOLUTIONS COMPARISON

Критерії відбору рішень: відкритий код, self-hosted, активна підтримка
станом на 2025 р., явна інтеграція з WireGuard (IPsec/OpenVPN виключено).

**Comparison table (Таблиця «Порівняння існуючих рішень…», ch.1):**

| Критерій | DefGuard | Firezone | NetBird | Tailscale/Headscale | WAG |
|---|---|---|---|---|---|
| Механізм 2FA | PSK-токен + TOTP/FIDO | OIDC (MFA у IdP) | OIDC (MFA у IdP) | OIDC (MFA у IdP) | TOTP (вбудований) |
| Точка примусу | Управляюча площина | Видача ключів | Видача ключів | Видача ключів | Маршрутизація |
| Стандартний WG-клієнт | Ні (власний) | Так | Ні (власний) | Ні (власний) | Так |
| Self-hosted | Так | Так | Так | Headscale: Так | Так |
| Залежність від IdP | Ні | Так | Так | Так | Ні |
| Стек технологій | Rust | Elixir/Rust | Go | Go | Go |
| Управління ключами | Так | Так | Так | Так | Ні |

**Ключове спостереження:** жодне рішення не задовольняє **водночас** усі чотири
вимоги, які закриває розроблена система:
1. підтримка **стандартного WireGuard-клієнта**;
2. **відсутність залежності від зовнішнього IdP**;
3. **власний механізм TOTP**;
4. **повноцінне управління ключами**.

Найближчі: **DefGuard** має власний TOTP + керування ключами + незалежність від
IdP, але **не підтримує стандартний WG-клієнт** (потрібен власний). **WAG** має
вбудований TOTP + стандартний клієнт + незалежність від IdP, але **не має
управління ключами**. Наша система — єдина, що ставить «так» у всіх чотирьох.

**Окрема таблиця (ch.2) «наша система проти DefGuard» (peer lifecycle vs PSK-токен):**
- Механізм обмеження: DefGuard — PSK замінюється на невалідний; наша — вузол видаляється з `wg0`.
- Прозорість: DefGuard — треба розуміти PSK; наша — «вузол або є, або ні».
- Стандартний WG-клієнт: DefGuard — Ні; наша — Так (будь-який).
- Складність реалізації: DefGuard — Висока (синхронізація PSK); наша — Низька (два subprocess-виклики).

---

## 8. BENCHMARK RESULTS (§3.10, EXACT numbers)

### Testbed config (Таблиця «Параметри вузлів випробувального стенду»)
- **VPS A (сервер):** UpCloud **PL-WAW1**, IP 81.27.101.178.
- **VPS B (клієнт):** UpCloud **DE-FRA1**, IP 94.237.94.30.
- ОС обох: **Ubuntu Server 26.04 LTS (Resolute Raccoon)**, **ядро 7.0.0-14**.
- Ресурси кожного: **1 vCPU / 2 ГБ RAM / 20 ГБ**.
- Виміряна RTT: **23,94 мс ± 0,06 мс** (медіана, N=100).
- WireGuard — **ядерний модуль** `wireguard.ko` (без `wireguard-go`), порт 51821.
- OpenVPN — статичний ключ, **AES-256-CBC + HMAC-SHA256**, UDP 1194.
- iperf3; CPU: `mpstat` (%soft для WG), `pidstat` (%cpu для OpenVPN). N=5 повторень.

### HEADLINE FIGURES
- **Паритет із чистим WireGuard у межах 1%:** tcp_t різниця **1,0%** (890 vs 881 Мбіт/с);
  tcp_p — **0%** (обидва 917 Мбіт/с); UDP-поріг — той самий **399 Мбіт/с**.
- **Час встановлення тунелю: 1571 мс (наша система) проти 92 мс для `wg-quick up`** — у **17 разів** більше.

### Затримка у стані спокою (мс, N=5)
| Сценарій | Медіана ± СКВ | p95 |
|---|---|---|
| Без VPN (базовий) | 24,00 ± 0,04 | 24,08 |
| WG plain (ядро) | 24,20 ± 0,00 | 24,20 |
| **Ця система (WG+2FA)** | **24,20 ± 0,00** | **24,20** |
| OpenVPN (AES-256-CBC) | 24,40 ± 0,05 | 24,40 |

### Затримка під навантаженням (мс, N=5) — bufferbloat
| Сценарій | p95 | Bufferbloat |
|---|---|---|
| Без VPN | 24,20 | +0,12 |
| WG plain (ядро) | 26,60 | +2,40 |
| **Ця система (WG+2FA)** | **27,26** | **+3,06** |
| OpenVPN | 24,88 | +0,48 |

### Пропускна здатність TCP/UDP (Мбіт/с, N=5, iperf3, 60 с)
| Сценарій | tcp_t (1 потік) | tcp_p (4 потоки) | Δp-t,% | UDP (1-й крок втрат) |
|---|---|---|---|---|
| Без VPN | 944 ± 57 | 990 | +4,9 | 799 |
| WG plain (ядро) | **890 ± 2,9** | 917 ± 35 | +3,0 | 399 |
| **Ця система (WG+2FA)** | **881 ± 2,1** | **917 ± 3,1** | +4,1 | 399 |
| OpenVPN (AES-256-CBC) | 54,5 ± 2,4 | 74,3 ± 0,9 | +36,3 | 397 |

- WireGuard tcp_t у **16,3×** більше за OpenVPN; tcp_p у **12,3×**.
- Δp-t WireGuard 3–4% vs OpenVPN 36% — «TSO-асиметрія» як архітектурний маркер
  (ядерна площина даних vs userspace).

### Завантаження CPU сервера під час TCP-тесту (N=5)
| Сценарій | %soft tcp_t | %soft tcp_p | Метод | Витрати ЦП на 1 Мбіт/с |
|---|---|---|---|---|
| WG plain (ядро) | 20,56 ± 0,36 | 22,49 ± 0,86 | mpstat %soft | ≈0,023% |
| **Ця система (WG+2FA)** | **34,80 ± 0,72** | **37,56 ± 0,29** | mpstat %soft | **≈0,040%** |
| OpenVPN | 13,05 ± 0,29 | 16,76 ± 0,20 | pidstat %cpu | ≈0,240% |

- OpenVPN ≈0,240% CPU/Мбіт/с — у **10,4×** більше за WireGuard (≈0,023%).
- Вища CPU нашої системи (34,8% vs 20,6% WG plain) — **не від шифрування**, а
  від мережевого namespace Docker (veth-пара + netfilter). Площина даних —
  той самий `wireguard.ko`; 2FA існує **виключно у площині керування**.
- ⚠️ %soft (mpstat) та %cpu (pidstat) **не порівнювані напряму** — лише
  нормалізована колонка «на 1 Мбіт/с».

### Час введення у тунель / онбординг (мс, N=5)
| Сценарій | Медіана | Примітка |
|---|---|---|
| WG plain (ядро) | **92** | `wg-quick up` + ping-цикл |
| **Ця система (WG+2FA)** | **1571** | POST /register → POST /login (TOTP) → реєстрація ключа → `wg-quick up` |
| OpenVPN | 82 | `openvpn --daemon` + ping (статичний ключ оминає TLS; реально 200–400 мс у PKI) |

### ⚠️ WEAKNESS TO ADDRESS (the one gap)
**Онбординг 1571 мс vs 92 мс** (у 17×; conclusions кажуть «+1479 мс»). Це
**одноразова** вартість 2FA-церемонії площини керування, сплачується при
кожному відновленні сесії. **Після встановлення з'єднання площина даних
ідентична чистому WireGuard — жодних додаткових затримок у потоці трафіку.**
Натомість дає **перевірюваний ідентифікатор користувача, прив'язаний до
кожного WireGuard-піра**. (Frame it as a deliberate, one-time trade-off, not
a steady-state penalty.)

---

## 9. FUNCTIONAL TESTS (7 сценаріїв, реальне розгортання)

Окремо від **149 автоматичних** тестів (unit/integration/security/E2E, усі
проходять). Функціональні — на реальному VPS UpCloud, Ubuntu 26.04 LTS, Docker
Compose. Усі **7 — «Успішно»**.

| № | Тест | Що доводить |
|---|---|---|
| 1 | Перевірка працездатності | `GET /api/v1/health` → status=healthy, wireguard=up: сервіс і WG-інтерфейс активні |
| 2 | Реєстрація з TOTP | `POST /auth/register` (HTTP 201, totp_secret + QR base64) + підтвердження зарахування (HTTP 200, success=true): 2FA enrollment працює |
| 3 | Двоетапна автентифікація | login → проміжний токен (requires_totp=true) → totp/verify → access_token (expires_in=86400): 2FA-flow видає JWT |
| 4 | Створення VPN-сесії та тунель | генерація ключів → `POST /vpn/sessions` (HTTP 201, assigned_ip + server_public_key) → `wg-quick up` → `wg show`: peer зареєстровано, тунель активний |
| 5 | Передача даних через тунель | `curl ifconfig.me` з тунелем → IP сервера; без тунелю → IP клієнта: трафік реально маршрутизується через VPN |
| 6 | Адміністрування | `GET /admin/users`, `GET /admin/sessions`, `DELETE /admin/sessions/{id}` (status=revoked): адмін керує користувачами/сесіями |
| 7 | Перевірка безпеки | (а) неправильний TOTP → 400; (б) звичайний user до /admin → 403; (в) запит без Authorization → 401: правила доступу дотримано |

**Автоматичне тестове покриття (Таблиця, 149 кейсів):** Автентифікація 24,
TOTP 18, VPN-сесії 32, WireGuard 15, Адміністрування 21, Безпека 19, E2E 12,
Фонові завдання 8. Усі проходять.

---

## 10. EXISTING DIAGRAMS / FIGURES (visuals to adapt)

> Total 17 рисунків + 14 таблиць у роботі. TikZ-діаграми векторні —
> легко перемалювати у слайди. Ключові:

**TikZ-діаграми (vector, ready to adapt):**
- `fig:noise_handshake` — **chapter1.tex** (§ Noise Protocol Framework, рядки ~160-205).
  Схема рукостискання WireGuard (шаблон Noise IK): Ініціатор↔Респондент,
  Handshake Init / Response, зашифрований трафік ChaCha20-Poly1305, 1-RTT.
- `fig:component_diagram` — **chapter2.tex** (§ Компонентна діаграма, рядки ~89-158).
  **Компонентна діаграма** системи: CLI-клієнт + WireGuard-клієнт → Caddy (TLS :443)
  → API Server (FastAPI :8000) → модулі (auth/totp/admin/sessions/tasks, wireguard)
  → SQLite (WAL) + інтерфейс wg0 (UDP :51820). Контейнери vpn-server та клієнтське середовище.
- `fig:auth_sequence` — **chapter2.tex** (§ Діаграма послідовності, рядки ~223-305).
  **Sequence diagram**: Клієнт ↔ API Server ↔ WireGuard. Три блоки — Реєстрація,
  Вхід (2FA), Встановлення тунелю. Показує всі ендпоінти, TTL токенів (5хв/24год),
  `wg set wg0 peer`, фінальний UDP-тунель :51820. **Найважливіша для defense.**
- `fig:er_diagram` — **chapter2.tex** (§ Діаграма зв'язків, рядки ~496-529).
  **ER-діаграма**: User (центр) — TOTPSecret (1:1), Device (1:N), VPNSession (1:N),
  SystemSettings (singleton); Device → VPNSession (1:N).

**Растрові скриншоти функціонального тестування (chapter3.tex, `images/func-*.png`):**
- `func-01` — health-ендпоінт (status=healthy, wireguard=up)
- `func-02` — реєстрація (HTTP 201, totp_secret/totp_qr_base64) + TOTP-підтвердження (200, success=true)
- `func-04` — login: requires_totp=true з проміжним токеном
- `func-05` — access_token після TOTP (expires_in=86400)
- `func-06` — створення VPN-сесії (201): assigned_ip + server_public_key
- `func-07` — `wg show`: активний тунель, рукостискання, лічильники
- `func-08` — `curl ifconfig.me` з тунелем: IP = VPN-сервер
- `func-09` — `curl ifconfig.me` без тунелю: IP повертається до оригінального
- `func-10` — `GET /admin/users`: список користувачів
- `func-11` — `DELETE /admin/sessions`: status=revoked
- `func-12` — неправильний TOTP → HTTP 400
- `func-13` — не-адмін до /admin/users → HTTP 403
- `func-14` — запит без Authorization → HTTP 401

**Таблиці-кандидати для слайдів:** Порівняння протоколів VPN (ch.1); Порівняння
методів 2FA (ch.1); Порівняння існуючих рішень (ch.1, §7 вище); Стек технологій
(ch.2, §4 вище); усі benchmark-таблиці (ch.3, §8 вище).

> **NOTE:** немає окремої діаграми розгортання Docker (опис лише текстовий) —
> можливий кандидат на новий слайд, якщо потрібен deployment view.
