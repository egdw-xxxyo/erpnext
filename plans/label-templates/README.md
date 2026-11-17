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
