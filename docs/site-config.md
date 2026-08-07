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

## Ручна перевірка (Manual Check)

```bash
# Перевірити конфіг всередині контейнера
docker compose -f docker-compose.yml exec -T backend cat sites/common_site_config.json
docker compose -f docker-compose.yml exec -T backend cat sites/frontend/site_config.json

# Перевірити значення ключа через bench
docker compose -f docker-compose.yml exec -T backend bench --site frontend execute frappe.conf.get --args '["server_script_enabled"]'
```
