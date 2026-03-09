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
| `erpnext/stock/doctype/item/item.py` | `_inherit_serial_fields_from_template()`: copies `serial_number_template` and `serial_no_series` from template to variant during `validate()`. `resolve_serial_number_template()`: resolves `{ATTR:...}` tokens to abbreviations. `_create_variant_bom_if_applicable()`: auto-creates variant BOM on `after_insert` |
| `erpnext/stock/doctype/item/item.js` | Calls resolve_series_for_item for variant Items |
| `erpnext/stock/serial_batch_bundle.py` | Resolves attribute tokens at serial number generation time |
| `erpnext/controllers/item_variant.py` | Copies serial_number_template, has_serial_no, serial_no_series to variants |
| `erpnext/manufacturing/doctype/job_card/job_card.json` | Unhidden serial_no field |
| `erpnext/manufacturing/doctype/bom/bom.py` | Added `create_variant_bom_from_template()` for auto-BOM on variant creation |
| `erpnext/stock/doctype/item_attribute_value/item_attribute_value.json` | Added `linked_item` Link field |
| `erpnext/stock/doctype/item_attribute/item_attribute.py` | Added `validate_linked_items()` validation |

### ERPNext Version

- ERPNext: v15.96.1
- Frappe: v15.99.0
- Docker-based deployment via `./deploy` script

## Development Guide — Patching Stock ERPNext Files

### Critical Architecture Constraint

This repo does NOT contain a full ERPNext codebase. It only contains **our custom/modified files**. The stock ERPNext code lives inside the Docker image (`erpnext:v15.96.1`). The `./deploy migrate` script copies specific files into running containers via `docker cp`.

### What the deploy script syncs

The `sync_files()` function in `./deploy` copies only explicitly listed files. See the `deploy` script (~line 77-100) for the full list. If you modify a file that is NOT in this list, **it will not be deployed**. You must add a new `docker cp` line.

### Safe way to modify stock ERPNext .py files

**DO NOT copy our full .py over the stock file** if our local copy has diverged from the stock ERPNext version (e.g., different imports, missing classes). This will break the container.

**Safe approach for adding functions to stock files (e.g., bom.py):**

1. Write the new function in our local repo file (for reference/source of truth)
2. Create a **patch script** in `erpnext/patches/` that appends the function to the stock file at deploy time
3. The patch script should:
   - Check if the function already exists (idempotent)
   - Import dependencies inside the function (not at module top-level) to avoid import conflicts
   - Fix any import incompatibilities between our local version and the stock version
4. Add the patch to the deploy script: `docker cp` the patch, then `docker exec` to run it

**Example:** `erpnext/patches/bom_variant_patch.py` — appends `create_variant_bom_from_template` to stock `bom.py`

**CRITICAL:** The deploy script restores the stock `bom.py` from the Docker image (`frappe/erpnext:v15.96.1`) before running the patch. This ensures the patch always starts from a known-good state. The stock file is extracted once with `docker run --rm` and then `docker cp`'d to each container before the patch runs.

**Safe approach for modifying stock files (e.g., item.py):**

Files listed in `sync_files()` (like `item.py`, `item.js`, `item_variant.py`) are copied wholesale. These MUST stay compatible with the stock ERPNext version:
- Do NOT add imports that don't exist in stock ERPNext (e.g., `ItemDetailsCtx` was added in a later version)
- Test imports with: `docker-compose -f .docker/pwd.yml exec -T backend python3 -c "from erpnext.module.path import thing"`

### Safe way to modify DocType JSON schemas

1. Edit the `.json` file locally (e.g., `item_attribute_value.json`)
2. Add the file to `sync_files()` in `./deploy` if not already there
3. Run `./deploy migrate` — Frappe will read the JSON and add/modify DB columns
4. **IMPORTANT:** If you set field values via Python BEFORE the migration runs, the column won't exist yet and values will be silently lost. Always deploy first, then set data.

### Debugging in the container

```bash
# Interactive console
docker-compose -f .docker/pwd.yml exec -T backend bench --site frontend console

# Test an import
docker-compose -f .docker/pwd.yml exec -T backend bench --site frontend console <<'PY'
from erpnext.manufacturing.doctype.bom.bom import create_variant_bom_from_template
print("OK")
PY

# Check if a DB column exists
docker-compose -f .docker/pwd.yml exec -T backend bench --site frontend console <<'PY'
import frappe
cols = frappe.db.sql("SHOW COLUMNS FROM `tabItem Attribute Value` LIKE 'linked_item'")
print(f"Exists: {bool(cols)}")
PY

# Check error logs
docker-compose -f .docker/pwd.yml exec -T backend bench --site frontend console <<'PY'
import frappe
errors = frappe.get_all("Error Log", fields=["method", "error"], limit=5, order_by="creation desc")
for e in errors:
    print(f"{e.method}: {e.error[:200]}")
PY

# Clear cache (required after DocType schema changes)
docker-compose -f .docker/pwd.yml exec -T backend bench --site frontend clear-cache

# Check file contents in container
docker-compose -f .docker/pwd.yml exec -T backend grep "function_name" /path/to/file.py
```

### Patch script gotchas (`erpnext/patches/bom_variant_patch.py`)

The patch script modifies stock `.py` files at deploy time. These are the hard-won rules:

1. **Naive string replacement breaks assignments.** `content.replace("self.foo", 'self.get("foo")')` will turn `self.foo = 0` into `self.get("foo") = 0` which is a SyntaxError. Always handle assignments separately with regex: replace `self.foo = X` with `pass` first, then replace reads with `.get()`.

2. **Python caches bytecode (`.pyc`).** After patching a `.py` file, if the container has a stale `.pyc`, the old (possibly broken) code still runs. The deploy script must clear `__pycache__` directories or restart containers. Symptoms: error messages reference code that no longer exists in the `.py` file.

3. **The patch must run on ALL containers** (backend, queue-short, queue-long, scheduler). Each container has its own filesystem. If you only patch `backend`, the queue workers still have the old code and will crash on background jobs.

4. **The patch must be re-entrant and handle previously-patched files.** If a previous run already replaced `self.foo` with `self.get("foo")`, a subsequent run won't find `self.foo` anymore. The patch must detect and fix BOTH the original and the already-patched (possibly broken) forms.

5. **Updating an existing function requires surgical removal.** Do NOT truncate from the function to EOF — this deletes stock functions that come after yours (e.g., `get_op_cost_from_sub_assemblies` was deleted this way, breaking Stock Entry). Instead: find the exact bounds of your function (from `def your_func` to the next top-level `def` or EOF) and replace only that range. The deploy script now restores the stock `bom.py` from the Docker image before each patch run, making the patch always start from a clean slate.

6. **Stock ERPNext v15.96.1 has fields/code that don't match the DocType JSON.** The Python code references `track_semi_finished_goods` and `is_sub_assembly_item` on BOM/BOM Item, but these fields don't exist in the DocType JSON or the database. The code sets them as dynamic attributes. The patch must handle:
   - `self.track_semi_finished_goods` — replace reads with `.get()`, replace assignments with `pass`
   - `d.is_sub_assembly_item` — replace reads in dict literals with `.get("is_sub_assembly_item", 0)`
   - `row.is_sub_assembly_item = X` — leave assignments as-is (Frappe allows setting arbitrary attrs on child docs)

7. **`get_mapped_doc()` does NOT copy all fields.** When mapping BOM → BOM (for variant BOM creation), custom or non-standard fields like `has_variants` on BOM Item rows are silently dropped (set to 0). You must manually restore them from the source document after mapping.

### MCP API vs bench execute

- **MCP `create_document` returns 500** for server errors but **417 for validation errors** (`frappe.throw()`). The 417 response does NOT include the error message — you only see "Request failed with status code 417".
- **To see the actual validation error**, use `bench execute frappe.client.insert` which prints the full traceback including the `frappe.throw()` message.
- **417 errors don't create Error Log entries** in the database. Only 500 errors do.
- **For debugging, use `frappe.log_error(title="...", message="...")`** — this always writes to `tabError Log` in the database, unlike `frappe.logger().info()` which may not be configured.

### Item variant creation via API

- **Use full `attribute_value`, not abbreviation.** E.g., `"attribute_value": "БпЛА Укропчик FO 15"`, NOT `"014"`. The abbreviation (`abbr`) is only for item code generation.
- **Always specify `item_group` explicitly.** Frappe does NOT auto-inherit `item_group` from the template. If omitted, it defaults to a group that may not exist in your locale.
- **Item Group names are locale-specific.** There is no "Готові вироби" — use `Продукція`. Check with: `SELECT name FROM \`tabItem Group\`;`

### Common pitfalls

| Problem | Cause | Fix |
|---|---|---|
| `ImportError: cannot import name 'X'` | Our local .py imports something not in stock ERPNext | Use imports inside the function body, or use the patch script approach |
| `DocType X not found` | DocType metadata was deleted from DB (e.g., by force-deleting with SQL) | Run `bench migrate` to recreate |
| Field values are None after setting them | Column didn't exist when values were set (migration hadn't run yet) | Deploy first (`./deploy migrate`), then set values |
| `bench console` caches old code | Python module cache persists within the console session | Exit and re-enter console, or restart the container |
| Function not available after deploy | File not in `sync_files()` list | Add `docker cp` line to deploy script |
| `SyntaxError: cannot assign to function call` | Patch replaced `self.foo = 0` with `self.get("foo") = 0` | Handle assignments separately in patch (use regex, replace with `pass`) |
| `.pyc` cache serves old broken code | Container has stale bytecode after patching `.py` | Clear `__pycache__` dirs and restart containers |
| Patch only fixes one container | Each container (backend, queue-short, etc.) has its own FS | Ensure deploy runs patch on ALL containers |
| `get_mapped_doc` loses custom fields | Non-standard fields silently reset to default (0/null) | Manually restore fields from source doc after mapping |
| MCP 417 with no error message | `frappe.throw()` returns HTTP 417 without details | Use `bench execute frappe.client.insert` to see actual error |
| `LinkValidationError: Could not find Item Group` | Item Group names are locale-specific | Check `tabItem Group` for actual names in your locale |
| Attribute values rejected on variant | Used abbreviation instead of full attribute_value | Always use the full value from `tabItem Attribute Value.attribute_value` |
| `serial_no_series` is NULL on variant | Template item has `serial_number_template` but no `serial_no_series` | Set `serial_no_series` on the template to the pattern from the Serial Number Template's `resulting_series` |
| Patch truncate-to-EOF deletes stock functions | Old approach removed everything from our function to EOF | Deploy now restores stock bom.py from Docker image before patching; patch finds exact function bounds |
| `ImportError: get_op_cost_from_sub_assemblies` | Patch deleted stock functions after our appended function | Always restore stock file before patching (deploy script does this automatically now) |

### Serial number template resolution

The serial number system uses a 3-step chain:

1. **Serial Number Template** DocType stores the pattern with `{ATTR:...}` tokens, e.g., `U.{ATTR:Номер ТУ}.{ATTR:Тип камери}.{ATTR:Призначення}.######`
2. **Template Item** must have BOTH `serial_number_template` (link to the template) AND `serial_no_series` (the pattern string with tokens). If `serial_no_series` is NULL, resolution won't fire.
3. **Variant inherits** both fields via `_inherit_serial_fields_from_template()` in `item.py` `validate()`, then `resolve_serial_number_template()` replaces `{ATTR:Номер ТУ}` → `014` using the abbreviation from `tabItem Attribute Value`.

**Key pitfall:** Creating variants directly via API (not via `create_variant()`) bypasses `copy_attributes_to_variant()`, so `serial_number_template` and `serial_no_series` aren't copied. The `_inherit_serial_fields_from_template()` method in `validate()` fixes this.

### Auto-BOM creation for variants

When a variant is created, `after_insert` calls `create_variant_bom_from_template()` (appended to stock `bom.py` by the patch):

1. Finds the template's `default_bom` (must be submitted, docstatus=1)
2. Looks for BOM Item rows with `has_variants=1` (e.g., CAM-TEMPLATE)
3. Maps variant attributes → `linked_item` via `tabItem Attribute Value.linked_item`
4. Uses `get_mapped_doc()` to clone the BOM, then replaces template items with linked items
5. **Must manually restore `has_variants`** from the template BOM after `get_mapped_doc()` (it silently drops this field)

### Current data setup

| Template | BOM | Frame | Variants |
|---|---|---|---|
| BPLA-UKROPCHYK (FO 15) | BOM-BPLA-UKROPCHYK-001 | FRAME-15 | BPLA-014-0DA-S, BPLA-014-0TA-S, BPLA-014-DTA-S, BPLA-014-0DA-T |
| BPLA-UKROPCHYK-10 (FO 10) | BOM-BPLA-UKROPCHYK-10-001 | FRAME-10 | BPLA-010-0DA-S, BPLA-010-0TA-S, BPLA-010-DTA-S |

Serial number format: `U.{ТУ}.{камера}.{призначення}.######` → e.g., `U.014.0DA.S.000001`

### UOM and locale values

In the Ukrainian locale, standard values differ from English defaults:
- UOM "Nos" → `Одиниця`
- Item Groups: `Продукція`, `Сировина`, `підвузли`, `Витратні`, `Послуги`
- Warehouses: `В роботі - Ф`, `Готові вироби - Ф`, `Магазини - Ф`

Always check existing values with MCP tools or `frappe.get_all("UOM")` before hardcoding.

### Deleting test data

Frappe has strict deletion rules for submitted documents. Order matters:

1. Stock Entries (cancel → delete)
2. Serial and Batch Bundles (cancel → delete)
3. Job Cards (cancel → delete)
4. Work Orders (cancel → delete)
5. BOMs (cancel → delete)
6. Item variants (delete)
7. Item templates (delete)

Use `doc.flags.ignore_links = True` before cancel if there are link validation errors. As a last resort, use raw SQL:
```python
frappe.db.sql("UPDATE `tabBOM` SET docstatus=2 WHERE name=%s", name)
frappe.db.sql("DELETE FROM `tabBOM Item` WHERE parent=%s", name)
frappe.db.sql("DELETE FROM `tabBOM` WHERE name=%s", name)
```

**WARNING:** Force-deleting DocType records via SQL (e.g., deleting from `tabDocType`) will corrupt metadata. Only delete data records, never DocType definitions. If corrupted, `bench migrate` will recreate them.

## Further Reading

- Frappe Translation System: https://frappeframework.com/docs/user/en/translations
- GNU gettext (PO/MO format): https://www.gnu.org/software/gettext/
