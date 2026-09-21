---
name: translations-and-docs
description: "How ERPNext/Frappe Ukrainian translations load and where to add them (erpnext vs frappe uk.csv, PO/MO override order, cache), plus docs/ conventions and the Ukrainian ERPNext term table. Use when adding UI strings or writing docs."
---

# Translations and documentation

## Overview

Frappe v15 uses a dual translation system with CSV and PO/MO files. Understanding the loading order is critical.

## Translation Loading Priority

1. **CSV files** (loaded first): `apps/*/translations/{lang}.csv`
   - Frappe: `apps/frappe/translations/uk.csv`
   - ERPNext: `apps/erpnext/translations/uk.csv`

2. **MO files** (loaded second, overrides CSV): `apps/*/locale/{lang}/LC_MESSAGES/{app}.mo`
   - Frappe: `apps/frappe/locale/uk/LC_MESSAGES/frappe.mo`
   - ERPNext: `apps/erpnext/locale/uk/LC_MESSAGES/erpnext.mo`


## How to Add New Translations

### ERPNext translations

**File**: `erpnext/translations/uk.csv`

```csv
"Plant Floor","Виробничий цех"
"Enable email notification","Увімкнути сповіщення електронною поштою"
```

**Deploy**: `./deploy migrate` (copies CSV to containers + clears cache)

### Frappe translations

**File**: `frappe/frappe/translations/uk.csv` (git submodule)

```csv
"Plant Floor","Виробничий цех"
```

**Deploy**:
1. Edit the file
2. Commit in submodule: `cd frappe && git add -A && git commit -m "message" && git push origin version-15 && cd ..`
3. `./deploy build` (frappe changes require image rebuild)

### Which file to edit?

- ERPNext strings (DocType labels, reports, manufacturing, stock, etc.) → `erpnext/translations/uk.csv`
- Frappe strings (core UI: buttons, dialogs, form controls, print, etc.) → `frappe/frappe/translations/uk.csv`
- If unsure, search both files for the English text: `grep "English Term" erpnext/translations/uk.csv frappe/frappe/translations/uk.csv`

### Common issues
- Translation not showing → `bench clear-cache`, verify exact English source text
- CSV loads first, PO/MO files override — for quick fixes, CSV is sufficient
- After any translation change, always clear cache


## Documentation Conventions

### Language

All documentation in `docs/` MUST be written in **Ukrainian with English references in parentheses**.

Format: `Українська назва (English Name)`

Examples:
- `Наряд на роботу (Work Order)`
- `Карта завдань (Job Card)`
- `Норми (BOM)`
- `Товар (Item)`

### Translation Reference Table

Use these exact translations from `erpnext/translations/uk.csv` for consistency:

| English | Ukrainian |
|---|---|
| Work Order | Наряд на роботу |
| Job Card | Карта завдань |
| BOM | Норми |
| Item | Товар |
| Item Group | Група |
| Operation | Операція |
| Workstation | Робоча станція |
| Stock Entry | Рух ТМЦ |
| Manufacture | Виробництво |
| Serial No | Серійний номер |
| Serial Number Series | Серії серійних номерів |
| Quality Inspection | Перевірка якості |
| Quality Inspection Template | Шаблон перевірки якості |
| Raw Material | Сировина |
| Sub Assembly | Підвузли |
| Finished Goods | Готові вироби |
| Plant Floor | Виробничий цех |
| WIP Warehouse | Склад "В роботі" |
| Has Serial No | Має серійний номер |
| Is Stock Item | Товар на складі |
| Include Item In Manufacturing | Включити предмет у виробництво |
| With Operations | З операцій |
| Use Multi-Level BOM | Використовувати багаторівневі Норми |
| Skip Material Transfer | Пропустити переміщення матеріалів |
| Material Transfer for Manufacture | Матеріал для виробництва передачі |
| Inspection Required before Delivery | Огляд обов'язковий перед поставкою |
| Workplace | Робоче місце |

### Where to Add Translations

1. **ERPNext UI strings**: Edit `erpnext/translations/uk.csv`
2. **Frappe UI strings**: Edit `frappe/frappe/translations/uk.csv` (submodule)
3. **Documentation** (`docs/` folder): Write in Ukrainian, include English in parentheses on first mention
   - Look up terms with: `grep "^English Term," erpnext/translations/uk.csv`

4. **Documentation files**:
   - `docs/manufacturing-guide.md` — Manufacturing setup guide (Ukrainian)
