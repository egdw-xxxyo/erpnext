# ERPNext/Frappe Translation System

## Overview

Frappe v15 uses a dual translation system with CSV and PO/MO files. Understanding the loading order is critical.

## Translation Loading Priority

1. **CSV files** (loaded first): `apps/*/translations/{lang}.csv`
   - Frappe: `apps/frappe/translations/uk.csv`
   - ERPNext: `apps/erpnext/translations/uk.csv`

2. **MO files** (loaded second, overrides CSV): `apps/*/locale/{lang}/LC_MESSAGES/{app}.mo`
   - Frappe: `apps/frappe/locale/uk/LC_MESSAGES/frappe.mo`
   - ERPNext: `apps/erpnext/locale/uk/LC_MESSAGES/erpnext.mo`

## File Structure

```
erpnext/
├── erpnext/
│   ├── translations/          # CSV translations (primary)
│   │   └── uk.csv            # Ukrainian translations
│   └── locale/               # PO/MO translations (secondary)
│       ├── main.pot          # Template (source of truth for msgids)
│       ├── uk.po             # Ukrainian PO file
│       └── uk/LC_MESSAGES/
│           └── erpnext.mo    # Compiled from uk.po
└── frappe/ (inside Docker)
    ├── translations/
    │   └── uk.csv
    └── locale/
        ├── uk.po
        └── uk/LC_MESSAGES/
            └── frappe.mo
```

## How to Add New Translations

### Option 1: CSV Format (Recommended for Quick Additions)

**Location**: `erpnext/translations/uk.csv`

**Format**:
```csv
source text,translated text,context
"Plant Floor","Виробничий цех",
"Enable email notification","Увімкнути сповіщення електронною поштою",
```

**Steps**:
1. Find the English source text (msgid) in `erpnext/locale/main.pot`
2. Add a new line to `erpnext/translations/uk.csv`
3. Restart the Frappe container or run `bench clear-cache`

### Option 2: PO Format (For Bulk Updates)

**Location**: `erpnext/locale/uk.po`

**Format**:
```
msgid "Plant Floor"
msgstr "Виробничий цех"
```

**Steps**:
1. Edit `erpnext/locale/uk.po`
2. Compile to MO: `msgfmt uk.po -o uk/LC_MESSAGES/erpnext.mo`
3. Copy both PO and MO files to Docker container
4. Restart or clear cache

## Finding Missing Translations

### Check what keys exist in main.pot vs what's translated:

```bash
# Count all msgids in main.pot
grep -c '^msgid ' erpnext/locale/main.pot

# Count translated entries in uk.po
grep -c '^msgid ' erpnext/locale/uk.po

# Find missing keys
python3 scripts/find_missing_translations.py
```

### Find where a specific translation is used:

```bash
# Search in main.pot for the source key
grep -A2 "Plant Floor" erpnext/locale/main.pot

# This shows the context (which DocType/file uses it)
```

## Docker Integration

### Existing translations in Docker image:

- `frappe/translations/uk.csv` - 4,798 entries (Frappe core)
- `erpnext/translations/uk.csv` - 8,744 entries (ERPNext)

### To add our custom translations:

```dockerfile
# Copy CSV translations (merged with existing)
COPY erpnext/translations/uk.csv /home/frappe/frappe-bench/apps/erpnext/translations/uk.csv

# Copy PO files
COPY erpnext/locale/uk.po /home/frappe/frappe-bench/apps/erpnext/locale/uk.po

# Copy compiled MO files
COPY erpnext/locale/uk/LC_MESSAGES/erpnext.mo /home/frappe/frappe-bench/apps/erpnext/locale/uk/LC_MESSAGES/erpnext.mo
```

## Translation Workflow

### For adding 1-10 new translations:
1. Edit `erpnext/translations/uk.csv` directly
2. Add comma-separated rows
3. Rebuild Docker image or copy to running container
4. Clear cache: `bench clear-cache`

### For bulk updates (100+ translations):
1. Update `erpnext/locale/uk.po`
2. Use `scripts/po_to_csv.py` to convert PO → CSV
3. Merge with existing `erpnext/translations/uk.csv`
4. Deploy and clear cache

## Common Issues

### Translation not showing up:
- Check CSV file syntax (proper quoting, no extra columns)
- Verify the exact msgid matches main.pot
- Clear cache: `bench clear-cache` or restart container
- Check loading priority (CSV loads first, MO overrides)

### Missing translations after update:
- New msgids added to main.pot by upstream
- Run comparison to find missing keys
- Add to CSV or update PO and recompile

### CSV vs PO confusion:
- **CSV is simpler** but less standard
- **PO is standard** for i18n but requires compilation
- Frappe loads CSV first, then MO files override
- Use CSV for quick fixes, PO for large updates

## Tools

### scripts/po_to_csv.py
Converts PO format to CSV format for Frappe consumption.

```bash
python3 scripts/po_to_csv.py erpnext/locale/uk.po erpnext/translations/uk.csv
```

### scripts/find_missing_translations.py
Finds msgids in main.pot that are not translated in uk.po.

```bash
python3 scripts/find_missing_translations.py > missing_keys.txt
```

## Translation Context

The `main.pot` file includes context comments showing where each translation is used:

```
#. Label of a Data field in DocType 'Workstation'
#: erpnext/manufacturing/doctype/workstation/workstation.json
msgid "Plant Floor"
msgstr ""
```

This helps understand the context when translating technical terms.

## Best Practices

1. **Always check main.pot first** to find the exact source text
2. **Use context comments** to understand technical terms
3. **Test in UI** after adding translations
4. **Keep CSV files clean** - no trailing commas, proper escaping
5. **Update both CSV and PO** if maintaining both formats
6. **Clear cache after changes** - translations are cached aggressively

## Language Codes

- `uk` = Ukrainian (українська)
- `da` = Danish (dansk)
- `en` = English (default, no translation needed)

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

Use these exact translations from `erpnext_translations_uk.csv` for consistency:

| English | Ukrainian | Source |
|---|---|---|
| Work Order | Наряд на роботу | erpnext_translations_uk.csv:10714 |
| Job Card | Карта завдань | erpnext_translations_uk.csv:5244 |
| BOM | Норми | erpnext_translations_uk.csv:1846 |
| Item | Товар | — |
| Item Group | Група | erpnext_translations_uk.csv:5115 |
| Operation | Операція | erpnext_translations_uk.csv:6294 |
| Workstation | Робоча станція | erpnext_translations_uk.csv:10743 |
| Stock Entry | Рух ТМЦ | erpnext_translations_uk.csv:9243 |
| Manufacture | Виробництво | erpnext_translations_uk.csv:5628 |
| Serial No | Серійний номер | erpnext_translations_uk.csv:8813 |
| Serial Number Series | Серії серійних номерів | erpnext_translations_uk.csv:8853 |
| Quality Inspection | Перевірка якості | — (corrected from "Сертифікат якості") |
| Quality Inspection Template | Шаблон перевірки якості | erpnext_translations_uk.csv:7574 |
| Raw Material | Сировина | erpnext_translations_uk.csv:7681 |
| Sub Assembly | Підвузли | — |
| Finished Goods | Готові вироби | erpnext_translations_uk.csv:4071 |
| Plant Floor | Виробничий цех | erpnext_translations_uk.csv:6860 |
| WIP Warehouse | Склад "В роботі" | erpnext_translations_uk.csv:10584 |
| Has Serial No | Має серійний номер | erpnext_translations_uk.csv:4465 |
| Is Stock Item | Товар на складі | erpnext_translations_uk.csv:5059 |
| Include Item In Manufacturing | Включити предмет у виробництво | erpnext_translations_uk.csv:4750 |
| With Operations | З операцій | erpnext_translations_uk.csv:10702 |
| Use Multi-Level BOM | Використовувати багаторівневі Норми | erpnext_translations_uk.csv:10398 |
| Skip Material Transfer | Пропустити переміщення матеріалів | erpnext_translations_uk.csv:9104 |
| Material Transfer for Manufacture | Матеріал для виробництва передачі | erpnext_translations_uk.csv:5699 |
| Inspection Required before Delivery | Огляд обов'язковий перед поставкою | erpnext_translations_uk.csv:4823 |
| Workplace | Робоче місце | — (custom DocType) |

### Where to Add Translations

1. **For new UI strings** (labels, messages in custom DocTypes):
   - Add to `erpnext_translations_uk.csv` (two-column: `English,Ukrainian`)
   - Or add to `erpnext/translations/uk.csv` (three-column: `English,Ukrainian,context`)

2. **For documentation** (`docs/` folder):
   - Write in Ukrainian
   - Every ERPNext term must include English in parentheses on first mention
   - Use the translation table above for consistent terminology
   - Look up terms in `erpnext_translations_uk.csv` with: `grep "^English Term," erpnext_translations_uk.csv`

3. **Documentation files**:
   - `docs/manufacturing-guide.md` — Manufacturing setup guide (Ukrainian)

### Deployment

- `./deploy init` — first-time setup (build image + start)
- `./deploy migrate` — deploy code changes (copies files to all containers, reloads gunicorn, runs bench migrate)
- `./deploy setup-prod` — enable production mode (disables nuke/destroy)
- `./deploy setup-dev` — enable dev mode

### Custom DocTypes

| DocType | Location | Purpose |
|---|---|---|
| Workplace | `erpnext/manufacturing/doctype/workplace/` | Worker portal with Job Card dashboard |
| Workplace Operation | `erpnext/manufacturing/doctype/workplace_operation/` | Child table for allowed operations |
| Workplace Employee | `erpnext/manufacturing/doctype/workplace_employee/` | Child table for assigned employees |
| Serial Number Template | `erpnext/stock/doctype/serial_number_template/` | Reusable serial number format builder with Item Attribute support |
| Serial Number Template Component | `erpnext/stock/doctype/serial_number_template_component/` | Child table for template parts (includes Item Attribute type) |

### Modified Core Files

| File | Change |
|---|---|
| `erpnext/stock/doctype/item/item.py` | Auto-resolves `{ATTR:...}` tokens in serial_no_series on variant save |
| `erpnext/stock/doctype/item/item.js` | Calls resolve_series_for_item for variant Items |
| `erpnext/stock/serial_batch_bundle.py` | Resolves attribute tokens at serial number generation time |
| `erpnext/controllers/item_variant.py` | Copies serial_number_template, has_serial_no, serial_no_series to variants |
| `erpnext/manufacturing/doctype/job_card/job_card.json` | Unhidden serial_no field |

### ERPNext Version

- ERPNext: v15.96.1
- Frappe: v15.99.0
- Docker-based deployment via `./deploy` script

## Further Reading

- Frappe Translation System: https://frappeframework.com/docs/user/en/translations
- GNU gettext (PO/MO format): https://www.gnu.org/software/gettext/
