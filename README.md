# ERPNext з українською локалізацією

ERPNext v15.96.1 + Frappe v15.99.0 з українськими перекладами та власними DocType.

## Вимоги

- Docker та Docker Compose
- Python 3 (для застосування конфігурації сайту)

## Швидкий старт

### Перший запуск

```bash
./deploy init
```

Це автоматично:
- Клонує frappe_docker
- Збирає Docker-образ з українськими перекладами
- Запускає контейнери
- Увімкне українську мову
- Застосує параметри з `site-config.json`

Після завершення система доступна за адресою http://localhost:8080

Логін: `Administrator` / Пароль: `admin`

Для зміни мови: Налаштування (Settings) → Мова (Language) → Українська

### Повсякденне використання

```bash
./deploy start          # Запустити, синхронізувати файли, застосувати конфігурацію, мігрувати
./deploy stop           # Зупинити контейнери
./deploy migrate        # Синхронізувати файли та запустити міграцію (без перезапуску)
```

### Деплой змін коду

Після редагування файлів локально:

```bash
./deploy migrate
```

Копіює власні DocType в контейнер, перезавантажує gunicorn, запускає `bench migrate` та очищає кеш.

### Управління середовищем

```bash
./deploy setup-prod     # Увімкнути production-режим (блокує деструктивні команди)
./deploy setup-dev      # Увімкнути dev-режим (всі команди доступні)
```

### Деструктивні команди (тільки dev)

```bash
./deploy nuke           # Зупинити та видалити всі дані
./deploy destroy        # Зупинити та видалити всі дані
```

## Конфігурація сайту

Файл `site-config.json` містить параметри, які автоматично застосовуються при `./deploy init` та `./deploy start`.

```json
{
  "server_script_enabled": 1
}
```

Додайте будь-які параметри Frappe — вони передаються через `bench set-config`.

| Параметр | Значення | Опис |
|---|---|---|
| `server_script_enabled` | `1` | Серверні скрипти (звіти, клієнтські скрипти через UI) |
| `enable_telemetry` | `0` | Вимкнути телеметрію |
| `mail_server` | `"smtp.example.com"` | SMTP сервер |

## Структура проекту

```
├── deploy                  # Скрипт деплою
├── Dockerfile.uk           # Docker-образ з перекладами
├── site-config.json        # Параметри конфігурації сайту
├── docs/
│   ├── manufacturing-guide.md   # Посібник з виробництва
│   └── script-reports.md        # Серверні скрипти та звіти
├── erpnext/
│   ├── translations/
│   │   └── uk.csv               # Українські переклади (CSV)
│   ├── locale/
│   │   ├── main.pot             # Шаблон перекладів
│   │   ├── uk.po                # Українські переклади (PO)
│   │   └── uk/LC_MESSAGES/
│   │       └── erpnext.mo       # Скомпільовані переклади
│   ├── manufacturing/doctype/
│   │   ├── workplace/           # Робоче місце (власний DocType)
│   │   ├── workplace_operation/ # Дозволені операції
│   │   └── workplace_employee/  # Призначені працівники
│   └── stock/doctype/
│       ├── serial_number_template/           # Шаблон серійних номерів
│       └── serial_number_template_component/ # Компоненти шаблону
└── .docker/                # frappe_docker (клонується автоматично)
```

## Документація

- [Посібник з виробництва](docs/manufacturing-guide.md) — налаштування виробництва, серійні номери, робочі місця
- [Серверні скрипти та звіти](docs/script-reports.md) — створення звітів та скриптів через UI
