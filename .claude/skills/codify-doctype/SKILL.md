---
name: codify-doctype
description: Graduate a desk-created (custom=1) DocType into repo-owned code with ./codify — export, fold Custom Fields/Property Setters, generate the migration patch, verify. Use when asked to "codify", "move a custom doctype to code", "make a custom doctype standard/default", or when the deploy drift report flags a DB-only DocType.
---

# Codify a custom DocType

Desk-created DocTypes carry `custom = 1` and live only in one site's database. They
never travel in the Docker image, never reach git, and are lost on a site rebuild.
Prototyping that way is intended — this is the graduation path.

Tools: `./codify` (host driver), `erpnext/utilities/doctype_codifier.py` (runs in the
container), `erpnext/utilities/doctype_drift.py` (advisory report, printed by `./deploy`).

## Why it is data-safe

- The table is `tab<DocType>` whether `custom` is 0 or 1 — flipping it moves no data.
- Fieldnames **are** the column names. The exporter keeps them verbatim, Cyrillic ones
  included (`тип_збірки`, `номер`, `назва`, `км`).
- Once `custom = 0`, the desk refuses to save the DocType without `developer_mode`
  (`frappe/frappe/core/doctype/doctype/doctype.py:335`) — the schema becomes code-owned
  by construction.

## Procedure

1. **See what is drifting.**
   ```
   ./codify drift --env prod
   ```

2. **Dry run.** Pick a target from the existing **stock** modules (`manufacturing`,
   `stock`, `quality_management`, `crm`, …) — the desk modules `УКРОПЧИК` / `Custom`
   have no repo home and are dropped.
   ```
   ./codify export "Department Timesheet" --module Manufacturing --env prod --dry-run
   ```
   Read the report: cluster members (child tables are pulled in automatically), Custom
   Fields folded, orphan Property Setters dropped, Client Scripts, Server Scripts to
   port, Ukrainian labels, warnings.

3. **Export for real** (same command without `--dry-run`). It writes
   `erpnext/<module>/doctype/<snake>/{__init__.py,<snake>.json,<snake>.py,<snake>.js}`,
   the patch `erpnext/patches/v15_0/codify_<snake>.py`, and appends the patch to
   `erpnext/patches.txt`. Existing files are skipped unless `--force`.

4. **Hand-finish** — the exporter deliberately does not guess here:
   - `_server_scripts.py.txt` is a dump, not code. Port each script to a whitelisted
     method on the controller, then delete the dump and the Server Script rows.
   - Review `<snake>.js` (concatenated Client Scripts) and `*.js.disabled`.
   - Replace Ukrainian labels in the JSON with English and add the pairs to
     `erpnext/translations/uk.csv` — mandatory, same commit.
   - Drop dead options (e.g. a `year` Select holding only `2026`).

5. **Lint.** `pre-commit run --files <changed files>` — must pass before commit.

6. **Verify on local**, never prod first:
   ```
   ./deploy build --silent
   ```
   Then check: the patch is in `tabPatch Log`, the list view opens, existing documents
   open with values intact, `custom` is 0 in `tabDocType`, and the drift report no
   longer lists the DocType.

7. **Release note** in `erpnext/release_notes/vYYYY.MM.DD.md` (Ukrainian), then deploy.

## Hard rules

- Never rename a fieldname as part of codifying. It is a DB column; a rename needs
  `frappe.model.rename_field` inside the patch, as a separate, deliberate step.
- Never codify a parent without its child tables in the same commit — the exporter
  collects them for you; do not delete them from the output.
- Never delete the DB table, and never `frappe.delete_doc("DocType", ...)`.
- Patches that must read a column before it disappears belong in `[pre_model_sync]`.
  Codify patches read nothing schema-bound, so `[post_model_sync]` (where `./codify`
  appends them) is correct.
- Prod deploys are blocked on untagged commits — tag the release.

## Precedent

`erpnext/patches/v15_0/codify_military_unit.py` is the hand-written original of the
generated patch: set `custom = 0`, drop the Property Setters, `frappe.reload_doc`,
`frappe.clear_cache`.
