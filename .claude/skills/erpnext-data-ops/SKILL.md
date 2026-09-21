---
name: erpnext-data-ops
description: "Bench console debugging recipes, MCP vs bench execute errors, item variant creation, serial number templates, auto-BOM, Ukrainian locale values and the order for deleting test data. Use when inspecting or changing site data."
---

# ERPNext data operations and pitfalls

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
