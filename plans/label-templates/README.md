# Label templates: HTML → visual designer migration (2026-11-17)

- `prod-backup-20261117-1343.json` — every prod Label Template (full documents) right before the
  migration, while all were still `editor_mode = HTML`. Source of truth for rolling one back.
- `visual-layouts-20261117.json` — the `layout_json` (and sample `preview_data` where the template had
  none) applied to prod. Each was checked by rendering the old HTML and the new layout side by side on
  prod with the same data before saving.

Roll a template back: set `editor_mode = HTML` and `html_template` to the value from the backup
(the Label Template version history has it too).

Images the layouts use live in the label image library (`Home/Label Images`): `Укропчик.jpeg`,
`ukropchik-emblem.svg`, `krykhke-*.svg`. `logo.jpeg` (АКБ Батарея 75x50) never existed on prod — those
logos were blank before and still are.

## Dev (2026-11-17)

- `dev_backup_20261117-1527.json` — all 48 dev templates before the migration.
- `visual-layouts-dev-20261117.json` — layouts applied on dev. 20 templates share prod's HTML and reuse
  its layouts; 9 are prod templates under their old names; the 20 «Бпак N» test copies are «Батарея 1»
  with their own fallback serial; «Пакування котушки» is «Батареї - Пакування» with its own title.

## Fix after the first prod run

The barcode lists (`repeat`) were spaced 15.6 mm per item instead of the old 13.97 mm and ended too
early, so a box with 5 items lost the 5th barcode. `visual-layouts-20261117.json` has the corrected
spacing (item 10.92 mm + gap 3.05 mm, list runs to the bottom of the label) for Бпак, Батарея 1,
Батареї - Пакування, Пакування котушки, БпЛА - Пакування.

`apply_layouts.py <api module> <layouts.json> ["Name|Name"]` re-applies layouts through the REST API
(the api module reads URL/key from `.mcp.json`; not committed).
