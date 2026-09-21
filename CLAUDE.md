## Related repos

- **`~/git/erpnext-mobile-kalheon/`** — Android application (Kotlin, Jetpack Compose, `ua.erpnextkalheon`). **The only supported OTDR client.** BLE scan/pair, auto-sync `.sor` download, workplace selection, taking the next spool off the day's plan, measurement upload, verdict display and label printing, plus Employee Chat. ERPNext side: `erpnext/devices/otdr_measurement_api.py` (the measurement API), `erpnext/manufacturing/spool_production.py` (spool endpoints: `next_spool` hands out the serial + Job Card, `finish_spool` closes it into stock — thin wrappers over the generic **Production Line** doctype engine in `erpnext/manufacturing/doctype/production_line/production_line.py`, which also opens the daily Work Orders; `Line Type` "Spool" today, other kinds of line reuse the engine), `erpnext/devices/workplace_dispatch.py` (runs the Workplace Script), `erpnext/devices/spool_qc.py` (QI + label + Job Card link), `erpnext/devices/sor_parser.py` (SOR parsing), `erpnext/devices/doctype/otdr_configuration/` (BLE/sync settings, pointed at by `Workplace.otdr_configuration`).

**Spool serials are never scanned.** A spool is produced, not received: it has no label until this flow prints one. `next_spool` picks a free Job Card, assigns its serial and marks it in progress; the app shows that serial and sends it back with the measurement.
- **`~/git/otdr-sync/`** — Desktop sync application (Python, PySide6). **Unsupported since the workplace measurement cutover**: it posts to the removed `otdr_api` endpoints and never sent a workplace. Kept for reference and for its BLE protocol constants only (`st3200_sync/ble/protocol.py`).
- **`~/git/otdr/`** — BLE protocol findings / reverse-engineering notes (`FINDINGS.md`).

## WhatsApp integration

WhatsApp lives in the **`frappe_whatsapp`** app (Meta Cloud API). **Use our fork, not upstream:**

- **Repo**: `https://github.com/egdw-xxxyo/frappe_whatsapp.git`, branch `master` (configured in `apps.json` / `apps.json.example`).
- **All WhatsApp app-side improvements** (webhook, message doctype, send path, templates, flows) go into this fork — commit + push there, then `./deploy build --silent` re-clones it into the image. There is no local submodule; the image clones from the remote.
- **ERPNext-side WhatsApp code** (not the app) lives under `erpnext/`: the Chat Center page `erpnext/crm/page/whatsapp_chat/` (+ its realtime handler `whatsapp_chat.py`) and the `WhatsApp Message` `doc_events` hook in `erpnext/hooks.py`. These stay in the erpnext repo.
- Decide by layer: transport/protocol/message-model change → fork; desk UI / CRM linking / realtime page → erpnext repo.
- Roadmap + gap analysis: `plans/whatsapp-crm-integration.md`.

## Chat attachments are thread-private (RULE)

A file uploaded into an Employee Chat belongs to that thread and **must never become a reusable
system-wide asset**. It is not offered in the file-library picker and cannot be attached to another
document. Enforced by `erpnext/crm/chat_files.py`, wired in `hooks.py` as
`permission_query_conditions["File"]` (hides `attached_to_doctype = "Chat Thread"` from every
`File` list query) plus a `File.before_insert` guard (`block_reuse`) that refuses a new File row
reusing a chat file's `file_url` — this is the path `frappe.handler.attach_file` takes for
"attach from library".

If a future feature needs to share a chat attachment elsewhere: **copy the file** (new File row,
new blob) and store a link back to the `Chat Message` on the copy, so users can navigate to the
conversation the file came from. Never re-point or re-attach the original.

Corollary for uploads: every chat file must end up with `attached_to_doctype = "Chat Thread"` —
otherwise it is invisible to `purge_thread` and leaks past the guards. Client-side previews that
are not the message's `attach` (the encrypted preview of a secret attachment) must be passed to
`send_message(extra_files=[...])`.

## Client apps

Device-side functionality lives in one supported client:
- **Android**: `~/git/erpnext-mobile-kalheon/` (Kotlin, Jetpack Compose) — the OTDR client
- **Desktop**: `~/git/otdr-sync/` (Python, PySide6) — **unsupported**, see Related repos

### Duplication rule

The former desktop/Android parity requirement no longer applies: the desktop client was
dropped when measurements moved to workplace scoping, so there is no second client to keep
in step. If desktop support is ever restored, the rule comes back with it — core sync being
BLE scan/pair, file discovery, auto-sync download, measurement upload, sync status UI and
ERP config.

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
- Tag the release commit (`git tag -a vYYYY.MM.DD -m "..."`).

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

## MCP server (`mcp-server/`)

Source, build and reconnect steps live in `mcp-server/CLAUDE.md` (loaded when working there). `.mcp.json` is gitignored and per machine — never commit it.

## Environment routing by URL

When the user shares an ERPNext URL, pick the MCP server by host IP:

| Host | Environment | MCP server prefix |
|---|---|---|
| `172.16.51.10` | prod | `mcp__erp-prod__*` (and `mcp__erp-prod-ssh-mcp__*` for shell) |
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

Translation mechanics (CSV vs PO/MO loading order, which `uk.csv` to edit, common issues) and documentation conventions (Ukrainian docs, term reference table): skill `translations-and-docs`.

## Modified Core Files

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

## Adding Custom Fields and Schema Changes

**New Custom Fields go in `erpnext/patches/setup_custom_fields.py`** (idempotent, runs on every deploy) — never fixtures, never one-time patches in `patches.txt`. Full procedure: skill `schema-changes`.

## Codifying desk-created DocTypes (`./codify`)

DocTypes built in the desk UI (`custom = 1`) exist only in that site's database and are lost on rebuild. Codify them with `./codify drift|export` — procedure in `.claude/skills/codify-doctype/SKILL.md`.

## Development Guide — Modifying ERPNext/Frappe Files
### Modifying stock ERPNext/Frappe files — MINIMISE UPSTREAM MERGE CONFLICTS

Technically you can edit any file directly. **Don't, unless there is no hook that does the job** — every edited stock line is a merge conflict waiting for the next upstream sync.

Measured on the 15.96.1 → 15.119.0 merge (1385 upstream commits):

| our change | files | conflicts |
|---|---|---|
| new files (our own modules) | 407 | **0** |
| edited stock files | 85 | 12 (47 overlapped upstream) |

**Deletions predict conflicts; additions barely do.** The 12 conflicting files deleted ~30 stock lines each (`job_card.js` 134, `serial_batch_bundle.py` 114, `bom.py` 49). The 35 files that overlapped upstream but merged clean deleted ≤ 13. `sales_order.js` added 524 lines with 0 deletions and its "conflict" was two blocks appended at the same EOF — resolved by keeping both.

**The rule: append, never rewrite. Prefer a hook over an edit.**

#### Order of preference

| Need | Do this | Already wired in `hooks.py` |
|---|---|---|
| New field on a stock DocType | `erpnext/patches/setup_custom_fields.py` (Custom Field) | — |
| Change `options` / `depends_on` / `default` / `field_order` | **Property Setter**, not a JSON edit | — |
| React to save/submit/cancel | `doc_events` | line ~355 |
| Replace controller logic | `override_doctype_class` | line ~47 (`Address`) |
| Replace a whitelisted API method | `override_whitelisted_methods` | line ~49 |
| Add form buttons / client behaviour | `doctype_js` → **separate** file under `erpnext/public/js/custom/` | line ~31 |
| Genuinely new server logic | new module in our own package, called from a hook | — |
| Last resort | append a new function at the **bottom** of the stock file | — |

#### Hard rules

- **Never re-export a stock DocType from the desk UI.** It reshuffles `field_order` and bumps `modified`, producing a guaranteed conflict with zero functional value. `supplier.json` conflicted for exactly this reason — its whole diff was drag-and-drop layout churn.
- **Never edit a stock DocType `.json` to add a field.** Use a Custom Field. `sales_order_item.json` and `task.json` conflicted here; both were avoidable.
- **Never hand-backport upstream code.** Cherry-pick the real upstream commit so git sees a shared ancestor. The hand-written `get_linked_docs` backport in `frappe/model/delete_doc.py` cost 3 conflict hunks *and* silently created a duplicate `def` (ruff `F811`) whose first definition became dead code.
- **Never rewrite the body of a stock function.** Append a new one and route to it via a hook. If you must change stock logic, keep the diff to the smallest possible number of deleted lines and say why in the commit message.
- Client-side additions in a `doctype_js` file **cannot conflict with upstream, ever**. `job_card.js`, `sales_order.js`, `purchase_receipt.js`, `item.js` and `quality_inspection.js` are all append-only additions that belong there.

#### Sync cadence

Merge `upstream/version-15` **monthly**, not once per 1000+ commits. Conflict cost grows superlinearly with drift, and long gaps hide bad edits: a broken query in `serial_batch_bundle.py` (querying `is_cancelled` / `type_of_transaction` / `item_code` on `Serial and Batch Entry`, which has none of those columns) survived months undetected because nothing ever forced a comparison against upstream.

```
git fetch upstream version-15
git merge-tree --write-tree --name-only HEAD upstream/version-15   # dry run, lists conflicts
```

After editing, commit, push, and rebuild on the server.

### Container debugging, data ops and pitfalls

Bench console recipes, MCP-vs-bench errors (a 417 hides the `frappe.throw` message), item variant API, serial number template resolution, auto-BOM, locale values and test-data deletion order: skill `erpnext-data-ops`.

**Never force-delete DocType definitions via SQL** (`tabDocType`) — it corrupts metadata. Only delete data records.

## Extra Frappe Apps (apps.json)

**Setting an app to `enabled: false` uninstalls it on the next deploy and deletes all of its DocType data.** Setup, forks and asset sync: skill `extra-frappe-apps`.

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

### IMPORTANT
- Always commit and push frappe changes BEFORE committing the submodule pointer in erpnext
- Never use `git add .` in erpnext root — it stages the frappe submodule pointer even if you didn't intend to
- The submodule tracks a specific commit, not a branch — after pulling frappe updates, you must `git add frappe` and commit in erpnext

## Frappe Insights (BI Tool)

Install and deploy integration, worker/asset sync constraints and translations: skill `frappe-insights`.
