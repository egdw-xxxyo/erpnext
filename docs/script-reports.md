# Серверні скрипти та звіти (Server Scripts & Script Reports)

## Передумови (Prerequisites)

Серверні скрипти повинні бути увімкнені в `site-config.json`:

```json
{
  "server_script_enabled": 1
}
```

Після зміни конфігурації запустіть `./deploy start` або `./deploy migrate`.

---

## Створення звіту (Script Report)

1. Перейдіть до `/app/report/new`
2. Заповніть:
   - **Report Name** — назва звіту
   - **Module** — модуль (напр. Stock, Manufacturing)
   - **Reference DocType** — базовий DocType (напр. Item, Work Order)
   - **Report Type** — оберіть "Script Report"
3. У полі **Script** напишіть Python-код
4. Збережіть та натисніть **Show Report**

---

## Синтаксис скрипту (Script Syntax)

### Правило відступів

Код скрипту **НЕ повинен мати відступів** на початку рядків. Frappe обгортає код у функцію, тому будь-який відступ на першому рівні викликає `SyntaxError`.

**Правильно:**
```python
data = frappe.db.sql("SELECT name FROM `tabItem` LIMIT 5", as_dict=1)
columns = [{"label": "Name", "fieldname": "name", "fieldtype": "Data", "width": 200}]
result = columns, data
```

**Неправильно** (зайві пробіли на початку):
```python
    data = frappe.db.sql("SELECT name FROM `tabItem` LIMIT 5", as_dict=1)
    columns = [{"label": "Name", "fieldname": "name", "fieldtype": "Data", "width": 200}]
    result = columns, data
```

Відступи всередині блоків (`if`, `for`, `def`) працюють як звичайно — заборонені лише відступи на **першому рівні**.

### Повернення результату

Є два способи повернути дані:

**Спосіб 1** — через змінну `data`:
```python
columns = [...]
result = frappe.db.sql("...", as_dict=1)
data = columns, result
```

**Спосіб 2** — через змінну `result`:
```python
columns = [...]
rows = frappe.db.sql("...", as_dict=1)
result = [result]
```

### Визначення колонок (Columns)

Кожна колонка — словник з полями:

| Поле | Опис | Приклад |
|---|---|---|
| `label` | Заголовок колонки | `"Назва товару"` |
| `fieldname` | Ключ у даних (з SQL) | `"item_name"` |
| `fieldtype` | Тип поля | `"Data"`, `"Float"`, `"Link"`, `"Currency"` |
| `options` | DocType для Link-полів | `"Item"`, `"Work Order"` |
| `width` | Ширина в пікселях | `200` |

### Фільтри (Filters)

Фільтри, визначені у секції **Filters** звіту, доступні через змінну `filters`:

```python
item_group = filters.get("item_group")

conditions = ""
if item_group:
conditions = f"AND item_group = '{item_group}'"

data = frappe.db.sql(f"""
SELECT name, item_name, item_group
FROM `tabItem`
WHERE disabled = 0 {conditions}
LIMIT 50
""", as_dict=1)

columns = [
{"label": "ID", "fieldname": "name", "fieldtype": "Link", "options": "Item", "width": 200},
{"label": "Назва", "fieldname": "item_name", "fieldtype": "Data", "width": 200},
{"label": "Група", "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 150}
]

data = columns, data
```

### Доступні об'єкти

У скрипті доступні стандартні об'єкти Frappe:

| Об'єкт | Опис |
|---|---|
| `frappe.db.sql()` | Виконати SQL-запит |
| `frappe.db.get_all()` | Отримати список записів |
| `frappe.db.get_value()` | Отримати одне значення |
| `frappe.utils` | Утиліти (дати, числа, форматування) |
| `filters` | Словник з фільтрами звіту |

---

## Приклади (Examples)

### Список товарів на складі (Stock Items)

```python
data = frappe.db.sql("""
SELECT name, item_name, item_group, stock_uom
FROM `tabItem`
WHERE disabled = 0 AND is_stock_item = 1
LIMIT 50
""", as_dict=1)

columns = [
{"label": "ID", "fieldname": "name", "fieldtype": "Link", "options": "Item", "width": 200},
{"label": "Назва", "fieldname": "item_name", "fieldtype": "Data", "width": 200},
{"label": "Група", "fieldname": "item_group", "fieldtype": "Link", "options": "Item Group", "width": 150},
{"label": "ОВ", "fieldname": "stock_uom", "fieldtype": "Data", "width": 100}
]

data = columns, data
```

### Наряди на роботу за статусом (Work Orders by Status)

```python
status = filters.get("status")

conditions = "WHERE docstatus = 1"
if status:
conditions += f" AND status = '{status}'"

data = frappe.db.sql(f"""
SELECT name, production_item, qty, produced_qty, status
FROM `tabWork Order`
{conditions}
ORDER BY creation DESC
LIMIT 50
""", as_dict=1)

columns = [
{"label": "Наряд", "fieldname": "name", "fieldtype": "Link", "options": "Work Order", "width": 200},
{"label": "Товар", "fieldname": "production_item", "fieldtype": "Link", "options": "Item", "width": 200},
{"label": "Кількість", "fieldname": "qty", "fieldtype": "Float", "width": 100},
{"label": "Виготовлено", "fieldname": "produced_qty", "fieldtype": "Float", "width": 100},
{"label": "Статус", "fieldname": "status", "fieldtype": "Data", "width": 120}
]

data = columns, data
```

---

## Клієнтські скрипти (Client Scripts)

Клієнтські скрипти виконуються в браузері та додають кнопки, валідацію, автозаповнення полів.

1. Перейдіть до `/app/client-script/new`
2. Оберіть **DocType** та **Script Type** = Form
3. Напишіть JavaScript-код

### Приклад — додати кнопку на форму товару (Item)

```javascript
frappe.ui.form.on('Item', {
refresh: function(frm) {
frm.add_custom_button(__('Показати залишок'), function() {
frappe.call({
method: 'frappe.client.get_list',
args: {
doctype: 'Bin',
filters: { item_code: frm.doc.name },
fields: ['warehouse', 'actual_qty']
},
callback: function(r) {
if (r.message && r.message.length) {
let msg = r.message.map(b => b.warehouse + ': ' + b.actual_qty).join('<br>');
frappe.msgprint(msg);
} else {
frappe.msgprint(__('Немає залишків'));
}
}
});
});
}
});
```

Клієнтські скрипти застосовуються одразу після збереження — перезавантажте сторінку з DocType для перевірки.
