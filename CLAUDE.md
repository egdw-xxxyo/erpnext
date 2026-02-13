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

## Further Reading

- Frappe Translation System: https://frappeframework.com/docs/user/en/translations
- GNU gettext (PO/MO format): https://www.gnu.org/software/gettext/
