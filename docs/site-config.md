# Конфігурація сайту (Site Configuration)

## Огляд (Overview)

Файл `site-config.json` у кореневій директорії проєкту містить налаштування, які `./deploy migrate` застосовує до контейнерів. Frappe використовує два конфіг-файли всередині контейнера:

| Файл | Шлях у контейнері | Опис |
|---|---|---|
| `common_site_config.json` | `sites/common_site_config.json` | Глобальний конфіг для всіх сайтів |
| `site_config.json` | `sites/frontend/site_config.json` | Конфіг конкретного сайту |

**ВАЖЛИВО:** Деякі ключі Frappe читає тільки з `common_site_config.json`. Скрипт `./deploy` автоматично визначає, куди записати кожен ключ.

## Поточні налаштування (Current Settings)

```json
{
  "server_script_enabled": 1,
  "insights_enabled": 0,
  "host_name": "http://frontend:8080"
}
```

| Ключ | Значення | Конфіг | Опис |
|---|---|---|---|
| `server_script_enabled` | `1` | **global** (`-g`) | Дозволяє Script Reports та Server Scripts. Frappe читає тільки з `common_site_config.json` |
| `insights_enabled` | `0`/`1` | site | Наш кастомний ключ — `./deploy` та `./insights` використовують для авто-встановлення Frappe Insights |
| `host_name` | URL | site | URL сайту для внутрішніх посилань |

## Глобальні vs локальні ключі (Global vs Site Keys)

Ключі зі списку `GLOBAL_KEYS` у `./deploy` записуються з прапорцем `-g` у `common_site_config.json`:

```bash
# Глобальний (common_site_config.json)
bench set-config -g server_script_enabled 1

# Локальний (site_config.json)
bench --site frontend set-config host_name "http://frontend:8080"
```

При додаванні нового ключа, який Frappe читає з `common_site_config.json`, додайте його до `GLOBAL_KEYS` у `./deploy`.

## Додаткові ключі Frappe (Additional Frappe Keys)

### Глобальні (`common_site_config.json`)

| Ключ | Тип | Опис |
|---|---|---|
| `server_script_enabled` | int | Увімкнути серверні скрипти та Script Reports |
| `enable_frappe_logger` | int | Увімкнути вивід `frappe.logger()` |
| `background_workers` | int | Кількість фонових воркерів |
| `mail_server` | str | SMTP сервер |
| `mail_port` | int | Порт SMTP |
| `use_ssl` | int | SSL для пошти |
| `mail_login` | str | Логін SMTP |
| `mail_password` | str | Пароль SMTP |
| `auto_email_id` | str | Email відправника |

### Локальні (`site_config.json`)

| Ключ | Тип | Опис |
|---|---|---|
| `host_name` | str | URL сайту |
| `developer_mode` | int | Режим розробника |
| `disable_website_cache` | int | Вимкнути кеш вебсайту |
| `logging` | int | Рівень логування (1=info, 2=debug) |
| `mute_emails` | int | Заглушити всі листи |
| `max_file_size` | int | Максимальний розмір файлу (МБ) |
| `fcm_service_account_json` | str | Абсолютний шлях до ключа сервісного акаунта Firebase — вмикає push-сповіщення в мобільному застосунку |

## Ручна перевірка (Manual Check)

```bash
# Перевірити конфіг всередині контейнера
docker compose -f docker-compose.yml exec -T backend cat sites/common_site_config.json
docker compose -f docker-compose.yml exec -T backend cat sites/frontend/site_config.json

# Перевірити значення ключа через bench
docker compose -f docker-compose.yml exec -T backend bench --site frontend execute frappe.conf.get --args '["server_script_enabled"]'
```

## Push-сповіщення (FCM)

Мобільний застосунок отримує push через Firebase Cloud Messaging. Серверу потрібні дві речі:

1. Пакет `firebase-admin` — уже стоїть в образі (`Dockerfile.full`).
2. Ключ сервісного акаунта Firebase (проєкт `erpnextkalheon`, той самий, що в `app/google-services.json` застосунку) і шлях до нього в `site_config.json`.

Ключ **не зберігається в git**. Він лежить у томі `sites`, тому переживає `./deploy build`, але не переживає перестворення сайту чи тому:

```bash
# покласти ключ у том sites (файл беремо з менеджера паролів, не з репозиторію)
docker compose cp /tmp/fcm-key.json backend:/home/frappe/frappe-bench/sites/fcm-service-account.json
docker compose exec -T -u root backend chown frappe:frappe /home/frappe/frappe-bench/sites/fcm-service-account.json
docker compose exec -T -u root backend chmod 600 /home/frappe/frappe-bench/sites/fcm-service-account.json
rm -f /tmp/fcm-key.json

# прописати шлях і перезапустити тих, хто читає конфіг
docker compose exec -T backend bench --site frontend set-config fcm_service_account_json /home/frappe/frappe-bench/sites/fcm-service-account.json
docker compose restart backend queue-short queue-long scheduler websocket
```

Перевірка (має вивести ідентифікатор повідомлення, надсилання несправжнє — `dry_run`):

```python
import frappe, firebase_admin
from firebase_admin import credentials, messaging
firebase_admin.initialize_app(credentials.Certificate(frappe.conf.get("fcm_service_account_json")))
print(messaging.send(messaging.Message(topic="erp-selftest"), dry_run=True))
```

Токени пристроїв застосунок реєструє сам (`erpnext.crm.page.employee_chat.employee_chat.register_fcm_token`) — вони видно в DocType **FCM Device Token**. Порожній список означає лише те, що жоден телефон ще не входив у систему після ввімкнення push.

Без ключа сервер мовчки не надсилає push (`_send_fcm_push` виходить одразу) — решта функцій працює як раніше.
