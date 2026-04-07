# Система дій сканера (Scanner Action System)

## Зміст (Table of Contents)

1. [Огляд (Overview)](#1-огляд-overview)
2. [Архітектура (Architecture)](#2-архітектура-architecture)
3. [DocTypes](#3-doctypes)
4. [API ендпоінт (API Endpoint)](#4-api-ендпоінт-api-endpoint)
5. [Командні штрих-коди (Command Barcodes)](#5-командні-штрих-коди-command-barcodes)
6. [Алгоритм обробки сканування (Scan Resolution Algorithm)](#6-алгоритм-обробки-сканування-scan-resolution-algorithm)
7. [Підтримувані дії (Supported Actions)](#7-підтримувані-дії-supported-actions)
8. [Управління станом (State Management)](#8-управління-станом-state-management)
9. [Приклади потоків (Example Flows)](#9-приклади-потоків-example-flows)
10. [Формат відповіді (Response Format)](#10-формат-відповіді-response-format)

---

## 1. Огляд (Overview)

Система дій сканера дозволяє апаратним сканерам штрих-кодів взаємодіяти з ERPNext через HTTP-ендпоінт. Кожен сканер автентифікується за допомогою API-ключа та виконує налаштовані дії: запуск/завершення Карток завдань (Job Cards), пошук за серійними номерами (Serial Numbers), сканування матеріалів тощо.

Ключова можливість — **командні штрих-коди (Command Barcodes)**: спеціальні коди, які переводять сканер у певний режим. Наприклад, сканування коду "ЗАВЕРШИТИ" переводить сканер у режим очікування Картки завдань, а наступне сканування штрих-коду Картки завдань — завершує її.

### Учасники системи

| Компонент | Опис |
|-----------|------|
| Налаштування сканера (Scanner Setup) | Конфігурація сканера: ключ API, користувачі, дії |
| Команда сканера (Scanner Command) | Визначення командних штрих-кодів |
| Журнал сканувань (Scanner Scan Log) | Аудит кожного запиту сканування |
| Дія сканера (Scanner Action) | Дочірня таблиця — дозволені дії для сканера |
| Redis-стан (Redis State) | Поточний режим сканера (з автоматичним тайм-аутом) |

---

## 2. Архітектура (Architecture)

```
┌──────────────┐     HTTP GET/POST      ┌──────────────────┐
│   Апаратний  │ ──────────────────────► │   handle_scan()  │
│   сканер     │  scanner_key + data     │   (allow_guest)  │
│  (Hardware)  │ ◄────────────────────── │                  │
└──────────────┘     JSON response       └────────┬─────────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                              ┌──────────┐ ┌──────────┐ ┌──────────────┐
                              │ Автент.  │ │ Журнал   │ │ Визначення   │
                              │ API-ключ │ │ Scan Log │ │ дії (Action  │
                              │          │ │          │ │  Resolution) │
                              └──────────┘ └──────────┘ └──────┬───────┘
                                                               │
                                                  ┌────────────┼────────────┐
                                                  ▼            ▼            ▼
                                           ┌───────────┐┌───────────┐┌───────────┐
                                           │ Команда?  ││ Режим у   ││ Дія за    │
                                           │ → Redis   ││ Redis?    ││ замовч.   │
                                           │   стан    ││ → handler ││           │
                                           └───────────┘└───────────┘└───────────┘
                                                               │
                                                  ┌────────────┼────────────┐
                                                  ▼            ▼            ▼
                                           ┌───────────┐┌───────────┐┌───────────┐
                                           │start_job()││complete_  ││scan_raw_  │
                                           │           ││  job()    ││material() │
                                           └───────────┘└───────────┘└───────────┘
                                              (workplace_portal.py — існуючі методи)
```

---

## 3. DocTypes

### 3.1 Дія сканера (Scanner Action) — дочірня таблиця

Дочірня таблиця для Налаштування сканера (Scanner Setup). Визначає, які дії доступні для конкретного сканера.

| Поле (Field) | Тип (Type) | Опис |
|-------------|------------|------|
| `action` | Select | Ключ дії: `start_job_card`, `finish_job_card`, `find_serial_finish`, `find_serial_start`, `scan_material` |
| `is_default` | Check | Дія за замовчуванням (коли сканер у стані "idle" та має лише одну дію) |
| `description` | Data | Опис дії для відображення |

### 3.2 Команда сканера (Scanner Command)

Окремий DocType для визначення командних штрих-кодів. Командний штрих-код — це спеціальний штрих-код, який не представляє товар чи серійний номер, а перемикає режим сканера.

| Поле (Field) | Тип (Type) | Опис |
|-------------|------------|------|
| `command_name` | Data (unique) | Назва команди, напр. "Завершити картку" |
| `barcode` | Data (unique, reqd) | Значення штрих-коду, напр. `CMD-FINISH` |
| `action` | Select (reqd) | Дія/режим: `start_job_card`, `finish_job_card`, `find_serial_finish`, `find_serial_start`, `scan_material`, `cancel` |
| `prompt_uk` | Data | Підказка українською, напр. "Скануйте картку завдань" |
| `prompt_en` | Data | Підказка англійською, напр. "Scan Job Card" |
| `is_active` | Check | Чи активна команда |

**Авто-назва (autoname)**: `field:command_name`

### 3.3 Журнал сканувань (Scanner Scan Log)

Логування кожного запиту сканування для аудиту та діагностики.

| Поле (Field) | Тип (Type) | Опис |
|-------------|------------|------|
| `scanner` | Link → Scanner Setup | Сканер, який надіслав запит |
| `timestamp` | Datetime | Час запиту |
| `raw_data` | Data | Отримані дані (штрих-код) |
| `resolved_action` | Data | Яка дія була визначена |
| `scanner_mode` | Data | Режим сканера на момент запиту |
| `target_document` | Dynamic Link | Цільовий документ (Job Card, Serial No тощо) |
| `target_doctype` | Link → DocType | Тип цільового документа |
| `status` | Select | `Processing`, `Success`, `Error`, `Command` |
| `result_message` | Small Text | Повідомлення результату |
| `error_message` | Small Text | Повідомлення помилки (якщо є) |

**Авто-назва (autoname)**: `SLOG-.#####`

### 3.4 Зміни до Налаштування сканера (Scanner Setup) — існуючий DocType

Нові поля, які додаються до існуючого DocType:

| Поле (Field) | Тип (Type) | Опис |
|-------------|------------|------|
| `workplace` | Link → Workplace | Робоче місце сканера (потрібно для start_job, complete_job) |
| `default_employee` | Link → Employee | Працівник за замовчуванням (для start_job) |
| `actions` | Table → Scanner Action | Дозволені дії |
| `idle_timeout` | Int (default: 60) | Тайм-аут режиму сканера (секунди) |

---

## 4. API ендпоінт (API Endpoint)

### URL

```
GET/POST /api/method/erpnext.manufacturing.doctype.scanner_setup.scanner_api.handle_scan
```

### Параметри (Parameters)

| Параметр | Обов'язковий | Опис |
|----------|-------------|------|
| `scanner_key` | Так | API-ключ сканера (64 символи hex) |
| `data` | Так | Дані сканування (штрих-код) |
| `action` | Ні | Явне визначення дії (обходить автовизначення) |

### Автентифікація (Authentication)

1. Метод позначений `@frappe.whitelist(allow_guest=True)` — сесія Frappe не потрібна
2. `scanner_key` порівнюється з `tabScanner Setup.api_key` де `is_active=1`
3. Якщо ключ не знайдено → HTTP 403
4. Після автентифікації: `frappe.set_user()` встановлюється на першого користувача з дочірньої таблиці `users` сканера — це забезпечує правильну перевірку прав доступу для подальших операцій (наприклад, submit Job Card)

### Приклад виклику

```bash
curl "https://erp.example.com/api/method/erpnext.manufacturing.doctype.scanner_setup.scanner_api.handle_scan?scanner_key=a1b2c3...&data=JC-MFG-00042"
```

---

## 5. Командні штрих-коди (Command Barcodes)

Командні штрих-коди — це спеціальні коди, які перемикають режим сканера замість виконання негайної дії. Вони друкуються на картках або наклейках біля робочих місць.

### Попередньо визначені команди (Predefined Commands)

| Штрих-код | Команда | Режим сканера | Підказка |
|-----------|---------|--------------|----------|
| `CMD-START` | Почати роботу | `start_job_card` | "Скануйте картку завдань для запуску" |
| `CMD-FINISH` | Завершити роботу | `finish_job_card` | "Скануйте картку завдань для завершення" |
| `CMD-MATERIAL` | Сканувати матеріал | `scan_material` | "Спочатку скануйте картку завдань" |
| `CMD-SERIAL-FINISH` | Знайти за серійним та завершити | `find_serial_finish` | "Скануйте серійний номер" |
| `CMD-SERIAL-START` | Знайти за серійним та почати | `find_serial_start` | "Скануйте серійний номер" |
| `CMD-CANCEL` | Скасувати/скинути | очищає стан | "Готово" |

### Як це працює

1. Оператор сканує командний штрих-код (напр. `CMD-FINISH`)
2. Система розпізнає його як команду → встановлює режим сканера в Redis
3. Повертає підказку: "Скануйте картку завдань для завершення"
4. Оператор сканує штрих-код Картки завдань
5. Система виконує дію `finish_job_card` з даними → завершує Картку завдань
6. Режим скидається (або залишається, залежно від налаштування)

---

## 6. Алгоритм обробки сканування (Scan Resolution Algorithm)

```
handle_scan(scanner_key, data, action=None):
│
├─ 1. Валідація scanner_key → отримати Scanner Setup
│     Помилка → 403 "Invalid scanner key"
│
├─ 2. Перевірка is_active
│     Неактивний → 403 "Scanner is disabled"
│
├─ 3. frappe.set_user(scanner.users[0].user)
│
├─ 4. Створити Scanner Scan Log (status="Processing")
│
├─ 5. Чи `data` є командним штрих-кодом?
│     ├─ ТАК (і action != "cancel"):
│     │   → Встановити режим у Redis (TTL = idle_timeout)
│     │   → Оновити лог (status="Command")
│     │   → Повернути {success: true, prompt: "...", mode: "..."}
│     │
│     └─ ТАК (action == "cancel"):
│         → Очистити Redis
│         → Повернути {success: true, message: "Reset", mode: null}
│
├─ 6. Чи передано явний параметр `action`?
│     └─ ТАК → Виконати дію з data, перейти до кроку 9
│
├─ 7. Чи є активний режим у Redis?
│     └─ ТАК → Направити до обробника режиму (mode handler)
│              → Обробник може:
│                 a) Виконати дію → очистити режим → крок 9
│                 b) Зберегти контекст → оновити Redis → повернути підказку
│
├─ 8. Сканер у стані idle (немає режиму):
│     ├─ Одна налаштована дія → використати її
│     ├─ Кілька дій → спробувати визначити за типом даних
│     └─ Не вдалося визначити → помилка "Scan a command barcode first"
│
└─ 9. Оновити Scanner Scan Log (status, result_message, target_document)
      → Повернути JSON відповідь
```

---

## 7. Підтримувані дії (Supported Actions)

### 7.1 `start_job_card` — Почати Картку завдань

| Крок | Опис |
|------|------|
| 1 | Розпізнати `data` як Job Card (пряме ім'я або через `find_job_card_by_barcode`) |
| 2 | Визначити працівника: `scanner.default_employee` або перший з time_logs |
| 3 | Викликати `workplace_portal.start_job(job_card, employee)` |
| 4 | Повернути результат |

**Потребує**: `workplace` на Scanner Setup

### 7.2 `finish_job_card` — Завершити Картку завдань

| Крок | Опис |
|------|------|
| 1 | Розпізнати `data` як Job Card |
| 2 | Визначити кількість: `job_card.for_quantity` (завжди повна кількість) |
| 3 | Викликати `workplace_portal.complete_job(workplace, job_card, qty)` |
| 4 | Повернути результат |

**Потребує**: `workplace` на Scanner Setup

### 7.3 `find_serial_finish` — Знайти за серійним номером і завершити

| Крок | Опис |
|------|------|
| 1 | Шукати Job Card за серійним номером (`_find_job_cards_by_serial_no`) |
| 2 | Якщо знайдено кілька → взяти перший за `expected_start_date` |
| 3 | Завершити як у `finish_job_card` |

### 7.4 `find_serial_start` — Знайти за серійним номером і почати

Аналогічно `find_serial_finish`, але викликає `start_job`.

### 7.5 `scan_material` — Сканувати матеріал (багатокроковий)

Ця дія є **двокроковою**:

| Крок | Що сканується | Дія системи |
|------|--------------|-------------|
| 1 | Картка завдань | Зберегти `job_card` у контексті Redis, повернути підказку "Скануйте матеріал" |
| 2 | Штрих-код матеріалу | Викликати `workplace_portal.scan_raw_material(workplace, job_card, barcode)` |

Після сканування матеріалу режим **залишається активним** (можна продовжувати сканувати матеріали для тієї ж Картки завдань). Для виходу — сканувати `CMD-CANCEL` або інший командний штрих-код.

---

## 8. Управління станом (State Management)

### Redis-ключ

```
scanner_state:{scanner_name}
```

### Структура стану

```json
{
  "mode": "finish_job_card",
  "sub_mode": null,
  "context": {
    "job_card": "JC-MFG-00043"
  },
  "set_at": "2024-01-15T10:30:00"
}
```

### Правила

| Правило | Опис |
|---------|------|
| TTL | Стан автоматично видаляється через `idle_timeout` секунд (за замовч. 60) |
| Перевизначення | Будь-який командний штрих-код замінює поточний стан |
| Скасування | `CMD-CANCEL` або тайм-аут очищують стан повністю |
| Контекст | Деякі дії (scan_material) зберігають контекст між кроками |
| Завершення дії | Одноразові дії (start/finish) очищують режим після виконання |
| Повторювані дії | scan_material залишається в режимі після виконання |

### Sub-modes для scan_material

| sub_mode | Очікує | Наступний крок |
|----------|--------|----------------|
| `waiting_for_jc` | Штрих-код Job Card | Зберегти JC в контексті, перейти до `waiting_for_material` |
| `waiting_for_material` | Штрих-код матеріалу | Виконати scan_raw_material, залишитись у `waiting_for_material` |

---

## 9. Приклади потоків (Example Flows)

### Потік 1: Завершення Картки завдань через командний штрих-код

```
Оператор                  Система                           Стан Redis
────────                  ───────                           ──────────
Сканує: CMD-FINISH    →   Розпізнано як команда             mode=finish_job_card
                      ←   {prompt: "Скануйте картку"}       TTL=60с

Сканує: JC-MFG-00042 →   mode=finish_job_card              (очищено)
                          → find JC → complete_job()
                      ←   {success: true, message:
                           "Картку JC-MFG-00042 завершено"}
```

### Потік 2: Пошук за серійним номером → завершення

```
Сканує: CMD-SERIAL-FINISH → mode=find_serial_finish         mode=find_serial_finish

Сканує: U.014.0DA.S.000001 → Пошук JC за серійним           (очищено)
                              → Знайдено JC-MFG-00042
                              → complete_job()
                           ← {success: true, message:
                              "Завершено JC-MFG-00042
                               (серійний U.014.0DA.S.000001)"}
```

### Потік 3: Сканування матеріалів (багатокроковий)

```
Сканує: CMD-MATERIAL   →  mode=scan_material                mode=scan_material
                           sub_mode=waiting_for_jc           sub=waiting_for_jc
                       ←   {prompt: "Скануйте картку завдань"}

Сканує: JC-MFG-00043  →   Зберегти JC в контексті           sub=waiting_for_material
                       ←   {prompt: "Скануйте матеріал"}     context.jc=JC-MFG-00043

Сканує: ITEM-123       →  scan_raw_material(jc, barcode)     (залишається)
                       ←   {success: true, message:
                            "Матеріал ITEM-123 зареєстровано"}

Сканує: ITEM-456       →  scan_raw_material(jc, barcode)     (залишається)
                       ←   {success: true}

Сканує: CMD-CANCEL     →  Очищено стан                       (очищено)
                       ←   {message: "Готово"}
```

### Потік 4: Сканер з однією дією (без командних кодів)

Якщо на сканері налаштована лише одна дія (`finish_job_card`), командні коди не потрібні:

```
Сканує: JC-MFG-00042 →   idle, одна дія = finish_job_card
                          → complete_job()
                      ←   {success: true}

Сканує: JC-MFG-00043 →   idle, одна дія = finish_job_card
                          → complete_job()
                      ←   {success: true}
```

### Потік 5: Помилка — невідома Картка завдань

```
Сканує: CMD-FINISH    →   mode=finish_job_card

Сканує: UNKNOWN-123   →   Job Card не знайдено               mode=finish_job_card
                       ←   {success: false,                   (режим збережено)
                            error: "Картку завдань не знайдено",
                            prompt: "Скануйте дійсну картку"}
```

---

## 10. Формат відповіді (Response Format)

### Успішна дія

```json
{
  "success": true,
  "action": "finish_job_card",
  "message": "Картку завдань JC-MFG-00042 завершено",
  "prompt": null,
  "mode": null,
  "scan_log": "SLOG-00001"
}
```

### Командний штрих-код (перехід у режим)

```json
{
  "success": true,
  "action": "command",
  "message": null,
  "prompt": "Скануйте картку завдань для завершення",
  "mode": "finish_job_card",
  "scan_log": "SLOG-00002"
}
```

### Помилка

```json
{
  "success": false,
  "action": "finish_job_card",
  "error": "Картку завдань не знайдено",
  "prompt": "Скануйте дійсну картку завдань",
  "mode": "finish_job_card",
  "scan_log": "SLOG-00003"
}
```

### Помилка автентифікації

```json
{
  "success": false,
  "error": "Invalid scanner key"
}
```

---

## Файли реалізації (Implementation Files)

| Файл | Призначення |
|------|-------------|
| `erpnext/manufacturing/doctype/scanner_action/` | Дочірня таблиця дій сканера |
| `erpnext/manufacturing/doctype/scanner_command/` | DocType командних штрих-кодів |
| `erpnext/manufacturing/doctype/scanner_scan_log/` | DocType журналу сканувань |
| `erpnext/manufacturing/doctype/scanner_setup/scanner_api.py` | Головний ендпоінт та обробники |
| `erpnext/manufacturing/doctype/scanner_setup/scanner_setup.json` | Додати нові поля |
| `erpnext/manufacturing/page/workplace_portal/workplace_portal.py` | Існуючі методи (без змін) |
