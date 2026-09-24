# Printer belongs to the bench, not to the script

## Why

`Workplace Script.workplaces` is now a table: one script can run at several benches
(commit `39b4cfbd40`). Printing is the one thing in those scripts that is still pinned to a
document instead of to the bench, so the second bench would print its labels on the first
bench's printer.

Today's state on prod:

| where the printer comes from | used by | problem |
|---|---|---|
| `Packing Template.label_printer` | `Упаковка.print_labels`, `Пакування — Коробки`, `Пакування FO — Котушки` | 23 templates, 21 of them pinned to `Тестовий`; the template says *what* to print, the bench says *where* |
| `Packing Template.label_printer` passed into `Упаковка FO.print_extra` | `Пакування FO — Котушки.packaging` | same printer, passed a second time by hand |
| nothing at all | `Виробництво - Доукомплектування та упаковка.packaging` (`pack.print_labels(pkg.name, tmpl_barcode)` — no `workplace`) | falls back to the template printer, bench ignored |
| `Workplace.printers` (default row) | `spool_qc.print_qc_label` only | the one flow that already does it right |

`Workplace.printers` exists (`Workplace Printer`: `label_printer`, `is_default`, at most one
default — `Workplace._validate_printers`), but only `Контроль оптики` fills it in.

## Target

One precedence, used everywhere:

```
printer picked in the app  →  bench printer (by purpose, then default)  →  document printer
(Packing Template / Item Label Template)  →  any printer the item names
```

The document printer stays as the last fallback so nothing goes dark during the rollout.

## Steps

### 1. Shared resolver (erpnext, new file)

`erpnext/devices/printer_resolution.py`:

- `workplace_printer(workplace, purpose=None)` — the bench's printer: the row whose `purpose`
  matches, else the `is_default` row. Accepts a name or a dict, like the current helper.
- `printers_for_workplace(workplace)` — every row, for the app picker.
- `resolve_printer(workplace=None, explicit=None, purpose=None, fallback=None)` — the full
  precedence above, returning `(printer, source)` so callers can log which tier answered.

Move the bodies of `spool_qc._workplace_printer` / `spool_qc.printers_for_workplace` here and
leave thin re-exports in `spool_qc.py` (the OTDR API imports them by name — append, never
rewrite). `print_qc_label` then calls `resolve_printer(...)` instead of its own `or` chain.

### 2. `Workplace Printer.purpose`

A bench can hold a spool printer and a box printer. Add a `purpose` Data field (same free-text
convention as `Item Label Template.purpose`, matched case-insensitively) so a script can ask
for `"Package"` or `"Passed"` and still fall back to the default row. Schema change goes in
`erpnext/patches/setup_custom_fields.py` if it stays a Custom Field, or straight into the child
DocType JSON since `Workplace Printer` is ours. Child JSON is ours → edit it directly.

### 3. Scanner Script `Упаковка` (v3)

- `print_labels(pkg_name, tmpl_name, workplace=None, e=None)`: resolve with
  `resolve_printer(workplace=workplace, purpose="Package", fallback=tmpl.label_printer)`.
  Keep `label_template` and `label_copies` on the Packing Template — those are *what*, not *where*.
- new `printer_for(workplace, tmpl_name)` helper so state scripts can show the printer and run
  `check_connection` against the one that will actually be used.
- `print_labels` already saves the last print per bench (`save_last_print(workplace, …)`), so
  `CMD-PRINT-AGAIN` needs no change — it reprints the job, and the job already carries its printer.

### 4. Scanner Script `Упаковка FO` (v2)

- `print_extra(pkg_name, printer, print_one, e=None)` → `print_extra(pkg_name, print_one, workplace=None, printer=None, e=None)`:
  resolve from the bench when the caller passes none. Keep the positional `printer` working for
  one release so an un-migrated script version does not break.

### 5. Workplace Scripts (via MCP, new versions — never edit the default version in place)

| script | state | change |
|---|---|---|
| `Пакування FO — Котушки` | `awaiting_template` | `_template_problem`: `check_connection` on the **resolved** printer; report "у робочого місця немає принтера" when the bench declares none and the template none either |
| `Пакування FO — Котушки` | `packaging` | drop `frappe.db.get_value("Packing Template", …, "label_printer")`; call `fo.print_extra(pkg.name, pack._print_job_once, workplace=e.workplace, e=e)` |
| `Пакування — Коробки` | `awaiting_template`, `template_loaded` | same printer check as above |
| `Пакування — Коробки` | `packaging` | pass `workplace=e.workplace` to `pack.print_labels` |
| `Виробництво - Доукомплектування та упаковка` | `packaging` | `pack.print_labels(pkg.name, tmpl_barcode, workplace=e.workplace, e=e)` (today it passes neither `workplace` nor `e`, and drops the result dict into `if printed:` as if it were a number — fix that too) |

Each edit: `add_workplace_script_version` → new version → `set_default_workplace_script_version`
after a scan test at the bench.

### 6. Data (prod)

- Fill `Workplace.printers` for every bench that prints: `Пакування`, `Пакування FO`,
  `Доукомплектування та упаковка`, `Контроль якості FO`, `Збірка рами`, `Прошивка бортів` —
  one row marked default, `purpose` set where a bench has two.
- Leave `Packing Template.label_printer` as-is; it is now only the fallback. Clearing the 21
  `Тестовий` rows is a separate, later cleanup once every bench is filled in.

### 7. Verify

- Scan test at `Пакування FO` end to end: label comes out at that bench's printer.
- Second bench added to the same script (`Пакування FO` + a new bench) — each prints locally.
- Bench with no printer and a template with one → still prints (fallback), log says `source=template`.
- Bench with neither → the display says so before the operator packs a box, not after.

## Out of scope (same class of hardcoding, separate tasks)

- `Упаковка FO.EXTRA_LABELS` — fixed label set in code; belongs on the Packing Template.
- `Упаковка FO.FG_WAREHOUSE = "Готова продукція FO - K"` — already overridable via the
  `fg_warehouse` context field; the constant is only the fallback.
- `Виробництво - Доукомплектування та упаковка`: `tmpl_barcode = "PKG-BPLA01"` hardcoded default
  and `OPERATION = "Доукомплектування"`.
