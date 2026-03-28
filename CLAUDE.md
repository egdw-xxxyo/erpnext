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
│   │   └── uk.csv            # Ukrainian translations (merged, replaces stock)
│   └── locale/               # PO/MO translations (secondary)
│       ├── main.pot          # Template (source of truth for msgids)
│       ├── uk.po             # Ukrainian PO file
│       └── uk/LC_MESSAGES/
│           └── erpnext.mo    # Compiled from uk.po
├── frappe/                    # Git submodule (egdw-xxxyo/frappe.git)
│   └── frappe/
│       ├── translations/
│       │   └── uk.csv        # Frappe Ukrainian translations (merged)
│       ├── locale/
│       │   └── uk.po         # Frappe Ukrainian PO file
│       └── printing/         # Custom print page modifications
└── docker-compose.yml         # Docker services configuration
```

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

### Deployment

- `./deploy init` — first-time setup (build image + start)
- `./deploy migrate` — deploy code changes (copies files to all containers, reloads gunicorn, runs bench migrate)
- `./deploy migrate --silent` — same as above but suppresses verbose output; only shows patch results and errors. **Claude should always use `--silent` when running deploy.**
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
- Frappe: v15.102.0 (git submodule at `frappe/`)
- Docker-based deployment via `./deploy` script
- Docker compose config: `docker-compose.yml` (committed in repo)

## Adding Custom Fields and Schema Changes for New Features

When a new feature requires Custom Fields or other schema changes, **always use a Frappe patch** so changes are applied automatically on test/prod via `bench migrate`.

### How to create a patch

1. Create a patch file in `erpnext/patches/v15_0/` (e.g., `add_battery_fields.py`):

```python
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def execute():
    create_custom_fields({
        "Purchase Receipt": [
            {
                "fieldname": "battery_serial",
                "fieldtype": "Data",
                "label": "Battery Serial",
                "insert_after": "items_section",
            }
        ]
    })
```

2. Register it in `erpnext/patches.txt`:
```
erpnext.patches.v15_0.add_battery_fields
```

3. Add the patch file to `sync_files()` in `./deploy` so it gets copied to containers.

4. `./deploy migrate` copies the file + runs `bench migrate` which executes the patch.

### Key behavior

- **Runs once**: tracked in `tabPatch Log`, never re-runs.
- **Hands-off after deploy**: if someone later removes a field manually, it stays removed.
- **Do NOT use fixtures** (`hooks.py` fixtures) for feature fields — fixtures re-sync on every migrate, preventing manual changes.
- `create_custom_fields()` is idempotent within the patch run (safe if field already exists).

### When to use patches vs other approaches

| Scenario | Approach |
|---|---|
| New feature needs Custom Fields | Patch with `create_custom_fields()` |
| New feature needs a new DocType | Add DocType JSON + `__init__.py` to repo, sync via deploy |
| Data migration (update existing records) | Patch with `frappe.db.sql()` or ORM |
| Something must run on every migrate | `after_migrate` hook in `hooks.py` |

## Development Guide — Patching Stock ERPNext Files

### Critical Architecture Constraint

This repo does NOT contain a full ERPNext codebase. It only contains **our custom/modified files**. The stock ERPNext code lives inside the Docker image (`erpnext:v15.96.1`). The `./deploy migrate` script copies specific files into running containers via `docker cp`.

### What the deploy script syncs

The `sync_files()` function in `./deploy` uses categorized arrays at the top of the function. Each category has a different way to add new items:

| Category | Array | How to add |
|---|---|---|
| Custom manufacturing DocTypes | `CUSTOM_MFG_DOCTYPES` | Add folder name to the array |
| Custom stock DocTypes | `CUSTOM_STOCK_DOCTYPES` | Add folder name to the array |
| Custom pages | `CUSTOM_MFG_PAGES` | Add folder name to the array |
| Custom reports | `CUSTOM_MFG_REPORTS` | Add folder name to the array |
| Stock file overrides | `STOCK_OVERRIDES` | Add `"local_path:container_path"` entry |
| Patched files | `PATCHED_FILES` | Add `"stock_path:patch_script"` entry |

**When creating new custom doctypes/pages/reports:** add the folder name to the appropriate array in `sync_files()`. This is a single line change. Do NOT add individual `docker cp` lines — the loops handle it.

**When modifying a stock file:** add a `"local:remote"` entry to `STOCK_OVERRIDES`.

**When patching a stock file (restore + patch approach):** add an entry to `PATCHED_FILES`.

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
- Test imports with: `docker compose -f docker-compose.yml exec -T backend python3 -c "from erpnext.module.path import thing"`

### Safe way to modify DocType JSON schemas

1. Edit the `.json` file locally (e.g., `item_attribute_value.json`)
2. Add the file to the appropriate array in `sync_files()` if not already there
3. Run `./deploy migrate` — Frappe will read the JSON and add/modify DB columns
4. **IMPORTANT:** If you set field values via Python BEFORE the migration runs, the column won't exist yet and values will be silently lost. Always deploy first, then set data.

### Debugging in the container

```bash
# Interactive console
docker compose -f docker-compose.yml exec -T backend bench --site frontend console

# Test an import
docker compose -f docker-compose.yml exec -T backend bench --site frontend console <<'PY'
from erpnext.manufacturing.doctype.bom.bom import create_variant_bom_from_template
print("OK")
PY

# Check if a DB column exists
docker compose -f docker-compose.yml exec -T backend bench --site frontend console <<'PY'
import frappe
cols = frappe.db.sql("SHOW COLUMNS FROM `tabItem Attribute Value` LIKE 'linked_item'")
print(f"Exists: {bool(cols)}")
PY

# Check error logs
docker compose -f docker-compose.yml exec -T backend bench --site frontend console <<'PY'
import frappe
errors = frappe.get_all("Error Log", fields=["method", "error"], limit=5, order_by="creation desc")
for e in errors:
    print(f"{e.method}: {e.error[:200]}")
PY

# Clear cache (required after DocType schema changes)
docker compose -f docker-compose.yml exec -T backend bench --site frontend clear-cache

# Check file contents in container
docker compose -f docker-compose.yml exec -T backend grep "function_name" /path/to/file.py
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
| Function not available after deploy | File not in `sync_files()` arrays | Add to the appropriate array in `sync_files()` (see "What the deploy script syncs") |
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

## Frappe Fork (git submodule)

The Frappe framework is a git submodule at `frappe/` pointing to `https://github.com/egdw-xxxyo/frappe.git` branch `version-15`.

### Committing changes

**ERPNext only (no frappe changes):**
```
git add erpnext/...
git commit -m "message"
git push
```

**Frappe only:**
```
cd frappe
git add ... && git commit -m "message" && git push origin version-15
cd ..
git add frappe
git commit -m "Update frappe submodule: <what changed>"
git push
```

**Both repos:**
```
# 1. Commit frappe changes first
cd frappe && git add ... && git commit -m "message" && git push origin version-15 && cd ..
# 2. Commit erpnext changes + submodule pointer together
git add frappe erpnext/...
git commit -m "Feature: description"
git push
```

### Pulling changes
```
./updateRepo
# Or: git pull && git submodule update --init
```

### Deploying after frappe changes
- **Frappe JS changes** → `./deploy init` (image rebuild, runs `bench build`)
- **Frappe Python/JSON only** → `./deploy migrate` (if file is in sync_files list)
- **ERPNext changes only** → `./deploy migrate`

### IMPORTANT
- Always commit and push frappe changes BEFORE committing the submodule pointer in erpnext
- Never use `git add .` in erpnext root — it stages the frappe submodule pointer even if you didn't intend to
- The submodule tracks a specific commit, not a branch — after pulling frappe updates, you must `git add frappe` and commit in erpnext

## Frappe Insights (BI Tool)

### Overview

Frappe Insights is an open-source BI tool installed as an additional Frappe app in the existing ERPNext bench. It runs inside the same containers — no separate deployment needed.

- **Source**: https://github.com/frappe/insights (branch `version-3` for Frappe v15)
- **Local clone**: `~/git/insights/` (for reference only, not used at runtime)
- **Access**: http://localhost:8080/insights (same host as ERPNext)
- **Credentials**: same as ERPNext (Administrator / admin, or any ERPNext user with Insights roles)

### Enabling/Disabling

Controlled by `insights_enabled` in `site-config.json`:

```json
{
  "server_script_enabled": 1,
  "insights_enabled": 1
}
```

- Set to `1`: `./deploy start`, `./deploy build`, `./deploy migrate` will auto-install Insights
- Set to `0` or remove: Insights is skipped (but not uninstalled if already present)
- Manual install/uninstall: `./insights install` / `./insights uninstall`

### How it works

The `./insights` script handles installation into the running ERPNext containers:

1. **`bench get-app insights`** on the backend container (clones from GitHub)
2. **`bench build`** (full rebuild of all apps — partial build corrupts `assets.json` hashes)
3. **`bench install-app insights`** on the site
4. **Syncs app code** to worker containers (queue-short, queue-long, scheduler) via tar pipe
5. **Copies built assets** to the frontend (nginx) container — required because nginx has a separate overlay mount for `sites/assets/` and can't see symlinks to backend's `apps/` directory

### How the deploy integration works

The `./deploy` script calls `./insights auto` twice during `start`, `build`, and `migrate`:

1. **Before restart**: syncs insights app code + assets to all containers
2. **Removes `insights` from `apps.txt`** right before `dc restart` — prevents workers from trying to import insights before files are synced
3. **After restart**: `./insights auto` runs again, re-syncs files (restart wipes non-persistent data), re-adds `insights` to `apps.txt`

This ordering is critical — if `insights` is in `apps.txt` when a worker starts but the module isn't synced yet, it causes `ModuleNotFoundError` spam in logs.

### Key architecture constraints

| Issue | Cause | Solution |
|---|---|---|
| `apps.txt` loses insights on restart | `configurator` service runs `ls -1 apps > sites/apps.txt` on every `dc up`, only sees frappe+erpnext from the Docker image | `./insights auto` re-adds `insights` to `apps.txt` after every restart |
| `ModuleNotFoundError` spam on scheduler/workers | Workers start and read `apps.txt` (has `insights`) before `./insights auto` syncs the module | `deploy` removes `insights` from `apps.txt` before restart, re-adds after sync |
| Frontend 404 on insights assets | nginx container has separate overlay mount for `sites/assets/`; symlinks to `apps/insights/...` are broken there | `fix_assets()` copies real files via `tar -ch` (follow symlinks) from backend to frontend container |
| Frontend 404 on frappe/erpnext CSS/JS after install | `bench build` regenerates `assets.json` with new hashes; frontend container still has old files from Docker image | `fix_assets()` copies ALL app assets (frappe, erpnext, insights) to frontend, not just insights |
| `bench build --app insights` corrupts asset hashes | Partial build regenerates `assets.json` with new hashes for ALL apps but only rebuilds insights bundles | Always do full `bench build` (no `--app` flag) when insights is present |
| `mysqlclient` fails to install | Insights depends on `ibis-framework[mysql]` which needs `pkg-config` + `libmariadb-dev` | `ensure_build_deps()` installs them via `apt-get` on all containers before `bench get-app` |
| Workers crash / can't import insights | Worker containers don't share app code filesystem with backend; files lost on every restart | `ensure_workers()` checks `import insights`, syncs via tar pipe + `pip install -e` if missing |
| `pip install -q` silently fails | Quiet mode hides build errors (e.g. missing `pkg-config`) | Always use `pip install -e` (no `-q`) and show tail of output |
| "Skipping fixture syncing" warnings during migrate | Frappe tries to sync insights fixtures during `bench migrate` — harmless, fixtures already exist from initial install | Safe to ignore; does not affect functionality |
| Old error logs persist in `docker-compose logs` | Docker accumulates logs across container restarts | `./deploy start --logs` uses `--since 0s` to only show new logs |
| `ModuleNotFoundError: No module named 'insights'` after uninstall | `bench uninstall-app` doesn't fully clean up: `tabDefaultValue.installed_apps` still lists insights, `tabDocType` records with `module=Insights` remain, `tabModule Def` "Insights" remains | `./insights uninstall` now does full DB cleanup via SQL: removes from DefaultValue, drops all Insights tables/DocTypes/Module Def/Roles |

### Build dependencies

Insights requires build deps not in the stock ERPNext image:
- `pkg-config`, `libmariadb-dev`, `gcc` (for `mysqlclient` / `ibis-framework`)
- Installed automatically by `./insights install` on all containers (backend + workers)
- **Not persistent** — lost on container restart/recreation, reinstalled automatically by `ensure_build_deps()`

### Data Sources

- A "Site DB" data source is auto-created on install, connecting to the ERPNext MariaDB
- Users need **Insights Admin** or **Insights User** role to see data sources
- Assign roles at: ERPNext → Setup → User → Roles

### Translation

Ukrainian translations are **hardcoded directly** in the Vue components in the forked repo (`egdw-xxxyo/insights.git`, branch `version-3`). The active frontend is `frontend/src2/` (NOT `src/`). The Frappe PO/MO translation system does NOT work reliably for Insights because:
- The v3 frontend (`src2/`) had no `__()` calls — strings were plain English
- Even with `__()`, translations load async and the app renders before they arrive
- `index.html` loads `src2/main.ts`, not `src/main.js` (confusing naming: `src2/` is v3, `src/` is v2)

To add/modify translations: edit the Ukrainian strings directly in `frontend/src2/*.vue` files in the fork repo, commit, push, then `./deploy start` will pull and rebuild.

### Files

| File | Purpose |
|---|---|
| `./insights` | Install/uninstall script |
| `./site-config.json` | Contains `insights_enabled` flag |
| `./deploy` | Calls `./insights auto` in `start`, `build`, `migrate` commands |

## Further Reading

- Frappe Translation System: https://frappeframework.com/docs/user/en/translations
- GNU gettext (PO/MO format): https://www.gnu.org/software/gettext/
- Frappe Insights docs: https://github.com/frappe/insights
