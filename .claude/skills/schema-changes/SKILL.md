---
name: schema-changes
description: "How to add Custom Fields, patches and schema changes in this ERPNext fork (setup_custom_fields.py, patches.txt, pre/post model sync). Use when a feature needs new fields or data migration."
---

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
