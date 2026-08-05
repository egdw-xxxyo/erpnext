## Related repos

- **`~/git/otdr-sync/`** — Desktop sync application (Python, Senter ST3200H-M / Novker NK1500 OTDR over BLE). Pulls `.sor` files from device, uploads to ERPNext via `OTDR.add_measurement_log` whitelisted method. See `~/git/otdr-sync/README.md`. ERPNext side: `erpnext/devices/doctype/otdr/otdr.py` (API + measurement ingestion), `erpnext/devices/doctype/otdr_configuration/` (sync settings shipped to desktop app), `erpnext/devices/doctype/device_script/` (Reflectometer scripts fired on SOR upload via `trigger_event="SOR Uploaded"`).
- **`~/git/otdr-sync-android/`** — Android sync application (Kotlin, Jetpack Compose). Core sync scope only: BLE scan/pair, auto-sync `.sor` download, ERPNext `submit_measurement` upload, sync status UI, ERP config. Same protocol constants as desktop (`~/git/otdr-sync/st3200_sync/ble/protocol.py`).
- **`~/git/otdr/`** — BLE protocol findings / reverse-engineering notes (`FINDINGS.md`).

## WhatsApp integration

WhatsApp lives in the **`frappe_whatsapp`** app (Meta Cloud API). **Use our fork, not upstream:**

- **Repo**: `https://github.com/egdw-xxxyo/frappe_whatsapp.git`, branch `master` (configured in `apps.json` / `apps.json.example`).
- **All WhatsApp app-side improvements** (webhook, message doctype, send path, templates, flows) go into this fork — commit + push there, then `./deploy build --silent` re-clones it into the image. There is no local submodule; the image clones from the remote.
- **ERPNext-side WhatsApp code** (not the app) lives under `erpnext/`: the Chat Center page `erpnext/crm/page/whatsapp_chat/` (+ its realtime handler `whatsapp_chat.py`) and the `WhatsApp Message` `doc_events` hook in `erpnext/hooks.py`. These stay in the erpnext repo.
- Decide by layer: transport/protocol/message-model change → fork; desk UI / CRM linking / realtime page → erpnext repo.
- Roadmap + gap analysis: `plans/whatsapp-crm-integration.md`.

## Multi-client parity (desktop + Android)

Device-side functionality lives in two client apps:
- **Desktop**: `~/git/otdr-sync/` (Python, PySide6) — full-featured
- **Android**: `~/git/otdr-sync-android/` (Kotlin, Jetpack Compose) — core sync only

### Duplication rule

**Core sync features must exist on both clients.** Core = BLE scan/pair, file discovery, auto-sync download, ERPNext `submit_measurement` upload, sync status UI, ERP config.

When changing any core-sync feature on one client, apply the equivalent change on the other in the same task. Do not merge desktop-only changes to core sync without a matching Android change (or an explicit note that Android is deferred).

**Desktop-only** (allowed to diverge): SOR metadata info dialog, manual send tools, advanced debug UI, dev workflow scripts.

**Android-only** (allowed): mobile-specific UX, background sync service, notifications.

### Server-side parsing invariant

SOR parsing should live in ERPNext only. Clients upload raw bytes. Do not re-implement SOR parsing on clients — it drifts, and silent client-side parse failures burn debugging time (see `_submit_to_erp` fallback path in `~/git/otdr-sync/st3200_sync/gui/main_window.py`).

## Release notes (MANDATORY when finishing work)

When finishing a feature or fixing a bug, **create or update the release-note file for the current release** in `erpnext/release_notes/`:

- One markdown file per release, named by version = git tag, `vYYYY.MM.DD.md` (add `.N` suffix for a 2nd+ release same day).
- Written **in Ukrainian**. First `# Heading` line = release title; the rest = body (bullet list of changes).
- If a file for today's release already exists, **append** your change to its body; otherwise create a new file.
- These files are the source of truth. On every `./deploy migrate` the `after_migrate` hook (`erpnext.manufacturing.doctype.release_note.release_note.sync_release_notes`) upserts a **Release Note** DocType record per file, so the changelog shows in the UI (`/app/release-note`) and the deployed version appears in **Help → About**.
- Tag the release commit (`git tag -a vYYYY.MM.DD -m "..."`). Prod deploy is blocked for untagged commits (`environment: "prod"` in `site-config.json`).

## Linting / CI (pre-commit) — MANDATORY before committing code

PRs run `.github/workflows/linters.yml`, which executes **pre-commit on ALL files** (`pre-commit/action@v3`) plus semgrep. Hooks: prettier, eslint, ruff (import sorter / linter / formatter). Config: `.pre-commit-config.yaml`, rules in `pyproject.toml` `[tool.ruff]`.

**Before committing any `.py` / `.js` change, run pre-commit and make it pass:**

```
pre-commit run --files <changed files>   # or --all-files
```

A local git hook is NOT installed (global `core.hooksPath` is set to `~/.git-hooks`, and `pre-commit install` refuses to overwrite that) — so the run is manual. If pre-commit isn't on PATH, use a venv: `python3 -m venv .venv-lint && .venv-lint/bin/pip install pre-commit`.

### Rules that this repo keeps violating

- **No duplicate `def` in a module** (ruff `F811`). This repo's pattern of *appending* functions/methods to stock files (`bom.py`, `quality_inspection.py`) has twice produced two defs of the same name — Python keeps only the last, so the first silently becomes dead code and its logic stops running. Always `grep -n "def <name>" <file>` before appending.
- **Names used in `TYPE_CHECKING` blocks must be imported** (`F821`) — child DocType classes referenced as `DF.Table["WorkplaceEmployee"]` need a real `from ... import WorkplaceEmployee` inside the `if TYPE_CHECKING:` block.
- **No stale `# noqa`** (`RUF100`) — `S102`/`F401` are not enabled here, so `# noqa: S102` is itself an error.
- No f-string without placeholders (`F541`), no unused locals (`F841`), no `for i in ...` where `i` is unused — use `_i` (`B007`).
- `isinstance(x, (A, B))` → `isinstance(x, A | B)` (`UP038`); `"...".format(...)` → f-string (`UP032`).

### Config notes (do not remove)

- `[tool.ruff.lint.isort] known-third-party = ["frappe"]` — the `frappe/` git submodule lives inside this repo, so without this ruff classifies frappe imports as first-party and rewrites the import block of **every upstream file**.
- `RUF002` / `RUF003` are ignored — Ukrainian docstrings and comments are full of Cyrillic characters ruff calls "ambiguous".

## Deploy command policy (STRICT)

**Only ever run `./deploy build --silent`.** Never run `./deploy migrate`, `./deploy start`, `./deploy init`, or any other `./deploy` subcommand. The other commands have repeatedly broken the running UI in this project, and `build` alone handles image rebuild + container restart + schema sync for our workflow.

`--silent` suppresses verbose Dockerfile / migrate output. On failure the script automatically prints the tail of the build log so you still see errors. Use it every time — the noise from non-silent mode wastes context.

If you believe a different command is required, stop and ask the user before running anything.

## UI Icons (default: Font Awesome)

**Use Font Awesome 4 icons by default for custom UI**, not emoji. FA4 is bundled in the frappe fork (`frappe/frappe/public/css/fonts/fontawesome/font-awesome.min.css`) and `<i class="fa fa-...">` works on every desk page.

- Markup: `<i class="fa fa-comment"></i>` (v4 syntax — `fa fa-<name>`, not `fa-solid`).
- Prefer FA over emoji for buttons, launchers, menu items, badges, and any new component icon.
- Frappe's native SVG sprite (`frappe.utils.icon("message", "md")`) is also fine and theme-aware — acceptable alternative when a matching glyph exists.
- Existing emoji in older code (e.g. chat compose 📎🎤) may stay; convert to FA when touching that code.

Example (chat bubble launcher): `erpnext/public/js/chat_bubble.js` `CB_LAUNCH` uses `fa fa-whatsapp` / `fa fa-users` / `fa fa-file-text-o`.

## Environment routing by URL

When the user shares an ERPNext URL, pick the MCP server by host IP:

| Host | Environment | MCP server prefix |
|---|---|---|
| `172.16.105.102` | prod | `mcp__erp-prod__*` (and `mcp__erp-prod-ssh-mcp__*` for shell) |
| `172.16.105.103` | dev | `mcp__erp-dev__*` (and `mcp__erp-dev-ssh-mcp__*` for shell) |
| `localhost` / `127.0.0.1` | local | `mcp__erp-local__*` |

URL-decode the path to get the document name (e.g. `BOM-%D0%91%D0%BF%D0%9B%D0%90%20U%2015...` → `BOM-БпЛА U 15...`). Default to the matching environment for any follow-up reads/writes unless the user says otherwise.

# ERPNext/Frappe Translation System

## Translation Rule (MANDATORY)

**Every user-facing string MUST be translated to Ukrainian, always.** When adding/editing any UI label, button, message, alert, dialog title, validation error, etc. in `.js`/`.py`/`.json` files:

1. Wrap the English string in `__()` (JS) or `_()` (Python)
2. Add the English→Ukrainian pair to `erpnext/translations/uk.csv` (or `frappe/frappe/translations/uk.csv` for Frappe core strings) in the same commit
3. Never ship an English-only string

This applies to every change, every time. No exceptions.

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
- `./deploy build` — rebuild Docker image and restart (required for any code/schema changes)
- `./deploy migrate` — run `bench migrate` on running containers (applies DB schema changes, runs patches)
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
| `erpnext/controllers/item_variant.py` | Copies serial_number_template, has_serial_no, serial_no_series to variants. `make_variant_item_code()` supports `variant_name_pattern` with `{AttributeName}` placeholders resolved via `short_name` (falls back to `abbr`) |
| `erpnext/manufacturing/doctype/job_card/job_card.json` | Unhidden serial_no field |
| `erpnext/manufacturing/doctype/bom/bom.py` | Added `create_variant_bom_from_template()` for auto-BOM on variant creation |
| `erpnext/stock/doctype/item_attribute_value/item_attribute_value.json` | Added `linked_item` Link field, `short_name` Data field (used in variant naming patterns) |
| `erpnext/stock/doctype/item/item.json` | Added `variant_name_pattern` Data field (pattern for variant item code/name using `{AttributeName}` placeholders) |
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
| New feature needs Custom Fields | Add to `erpnext/patches/setup_custom_fields.py` (runs on every deploy, idempotent) |
| New feature needs a new DocType | Add DocType JSON + `__init__.py` to repo, sync via deploy |
| Data migration (update existing records) | Patch with `frappe.db.sql()` or ORM |
| Something must run on every migrate | `after_migrate` hook in `hooks.py` |

**IMPORTANT:** Always add new Custom Fields to `erpnext/patches/setup_custom_fields.py`, NOT as one-time patches in `patches.txt`. This script runs on every deploy (`./deploy build/migrate`) and is idempotent — it skips fields that already exist. This ensures custom fields are automatically applied on prod when deploying.

## Codifying desk-created DocTypes (`./codify`)

DocTypes built in the desk UI carry `custom = 1` and exist **only in that site's database** — they never travel in the Docker image, never reach git, and are lost on a site rebuild. Prototyping that way is fine; leaving them there is not.

- `./codify drift --env prod|dev|local` — lists DocTypes that exist only in the DB. The same report is printed by `./deploy` after every migrate (advisory, never fails the deploy).
- `./codify export "<DocType>" --module <stock module> --env prod [--dry-run]` — exports the DocType and its child tables into `erpnext/<module>/doctype/...`, folds Custom Fields and Property Setters into the JSON, generates `erpnext/patches/v15_0/codify_<snake>.py` and registers it in `patches.txt`.

Target modules must be **existing stock modules** (`manufacturing`, `stock`, `quality_management`, `crm`, …) — the desk-only modules `УКРОПЧИК` / `Custom` have no repo home.

Flipping `custom` to 0 moves no data: the table is `tab<DocType>` either way and fieldnames (= column names) are kept verbatim. Server Scripts, Client Script review and English labels + `uk.csv` pairs are manual steps. Full procedure: `.claude/skills/codify-doctype/SKILL.md`. Implementation: `erpnext/utilities/doctype_codifier.py`, `erpnext/utilities/doctype_drift.py`. Precedent for the generated patch: `erpnext/patches/v15_0/codify_military_unit.py`.

Password-only SSH hosts: `export SSHPASS=... CODIFY_SSH_CMD='sshpass -e ssh'`.

## Development Guide — Modifying ERPNext/Frappe Files

### Architecture

This repo contains the **full ERPNext and Frappe source code**. The `Dockerfile.full` copies the entire `erpnext/` and `frappe/frappe/` directories into the Docker image, replacing the stock code:

```dockerfile
COPY --chown=frappe:frappe erpnext/ /home/frappe/frappe-bench/apps/erpnext/erpnext/
COPY --chown=frappe:frappe frappe/frappe/ /home/frappe/frappe-bench/apps/frappe/frappe/
```

This means you can **edit any ERPNext or Frappe file directly** — no patch scripts, no `docker cp`, no `sync_files()` arrays needed.

### Development workflow

1. **Edit files** locally in the repo (Python, JSON, JS — anything under `erpnext/` or `frappe/frappe/`)
2. **Commit and push** to the repo
3. **On the server**: pull changes, then `./deploy build` (rebuilds Docker image with new code + runs `bench build` for JS/CSS)
4. **Run** `./deploy migrate` if there are schema changes (new DocType fields, new patches)

### When to use which deploy command

| Change type | Command |
|---|---|
| Python code changes | `./deploy build` (rebuilds image, restarts containers) |
| DocType JSON schema changes (new fields, field order) | `./deploy build` then `./deploy migrate` |
| JS/CSS changes | `./deploy build` (includes `bench build`) |
| Frappe patches (in `patches.txt`) | `./deploy build` then `./deploy migrate` |
| Only running pending migrations | `./deploy migrate` |

### Modifying stock ERPNext/Frappe files

You can edit any file directly. Common examples:
- Add a field to a DocType → edit the `.json` file, add to `field_order` and `fields`
- Add/modify Python logic → edit the `.py` file directly
- Change client-side behavior → edit the `.js` file directly

After editing, commit, push, and rebuild on the server.

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

### Important notes

- **`get_mapped_doc()` does NOT copy all fields.** When mapping BOM → BOM (for variant BOM creation), custom or non-standard fields like `has_variants` on BOM Item rows are silently dropped (set to 0). You must manually restore them from the source document after mapping.

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
| `DocType X not found` | DocType metadata was deleted from DB (e.g., by force-deleting with SQL) | Run `bench migrate` to recreate |
| Field values are None after setting them | Column didn't exist when values were set (migration hadn't run yet) | `./deploy build` then `./deploy migrate`, then set values |
| `bench console` caches old code | Python module cache persists within the console session | Exit and re-enter console, or restart the container |
| Code changes not visible after deploy | Forgot to rebuild Docker image | `./deploy build` rebuilds the image with all source changes |
| `get_mapped_doc` loses custom fields | Non-standard fields silently reset to default (0/null) | Manually restore fields from source doc after mapping |
| MCP 417 with no error message | `frappe.throw()` returns HTTP 417 without details | Use `bench execute frappe.client.insert` to see actual error |
| `LinkValidationError: Could not find Item Group` | Item Group names are locale-specific | Check `tabItem Group` for actual names in your locale |
| Attribute values rejected on variant | Used abbreviation instead of full attribute_value | Always use the full value from `tabItem Attribute Value.attribute_value` |
| `serial_no_series` is NULL on variant | Template item has `serial_number_template` but no `serial_no_series` | Set `serial_no_series` on the template to the pattern from the Serial Number Template's `resulting_series` |
| Migration patch loses data when removing a DocType field | `bench migrate` runs in order: `[pre_model_sync]` patches → schema sync (drops columns) → `[post_model_sync]` patches | Patches that read a column being removed **must** be in `[pre_model_sync]` section of `patches.txt` |

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

## Extra Frappe Apps (apps.json)

Extra apps (HRMS, CRM, ...) are configured in `apps.json` in the repo root. The file is **gitignored** (per-environment config, like `site-config.json`) — copy `apps.json.example` to `apps.json` on each machine. Docker build fails without it:

```json
[
  { "name": "hrms", "repo": "https://github.com/egdw-xxxyo/hrms.git", "branch": "version-15", "enabled": true },
  { "name": "crm", "repo": "https://github.com/frappe/crm.git", "branch": "v1.77.3", "enabled": true }
]
```

- **Build time**: `Dockerfile.full` clones ALL listed apps (enabled or not) into the image, pip-installs them, runs `yarn install` if the app has a `package.json`, and adds them to bench `apps.txt` so `bench build` compiles their assets. Disabled apps stay in the image so `bench uninstall-app` can run (it needs the app code).
- **Deploy time**: `./deploy` (`ensure_extra_apps`) installs every `enabled: true` app on the site and **uninstalls** any `enabled: false` app that is still installed. **Uninstall deletes all of that app's DocType data from the DB.**
- Asset sync (`sync_built_assets`, `fix_assets`) picks up enabled apps dynamically from `apps.json`.
- To add an app: add an entry, then `./deploy build --silent`. To disable: set `enabled: false`, rebuild (data loss warning above applies).
- To customize an app's code: fork it (convention: `egdw-xxxyo/<app>`), point `repo` at the fork. Changes must be pushed to the fork — the image clones from the remote, there is no local submodule for extra apps (only `frappe/` remains a submodule).
- The old `hrms_app/` submodule was removed; HRMS now comes via apps.json.

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
