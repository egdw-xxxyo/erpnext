---
description: Update a Workplace Script on ERPNext via MCP
allowed-tools: mcp__erp-local__get_documents, mcp__erp-local__update_document, mcp__erp-dev__get_documents, mcp__erp-dev__update_document
argument-hint: <script-name> [environment]
---

# Update Workplace Script

The user wants to update a Workplace Script on their ERPNext instance. Follow these steps:

## 1. Determine target

- First argument: the Workplace Script name (e.g., "Пакувальник")
- Second argument (optional): environment — "local" (default) or "dev"
- Use `mcp__erp-local__*` tools for local, `mcp__erp-dev__*` for dev

## 2. Fetch current script

Use `get_documents` with:
- doctype: "Workplace Script"
- filters: `{"name": "<script-name>"}`
- fields: `["name", "script", "workplace", "is_active"]`

Show the user the current script content.

## 3. Discuss changes

Ask the user what they want the script to do. Then write the updated Python script.

## 4. Script writing rules

Workplace Scripts are Python code executed server-side in a sandboxed `exec()`. They must follow these conventions:

### Entry point
```python
def on_scan(e):
    # handle the scan event
    ...
```

### Event object (e) properties
| Property | Type | Description |
|---|---|---|
| `e.data` | str | Raw scanned string |
| `e.scan_type` | str | "workplace", "employee", "job_card", "serial_no", "item", "unknown" |
| `e.doc` | Document | Resolved Frappe document or None |
| `e.item_code` | str | Item code (for serial_no and item scans) |
| `e.barcode` | str | Original barcode (if resolved via Item Barcode) |
| `e.scanner` | Document | Scanner document |
| `e.workplace` | Document | Current Workplace document (from scanner context) |
| `e.employee` | str | Current Employee name (from scanner context) |
| `e.state` | StateProxy | Persistent state between scans (Redis-backed) |

### State API (e.state)
- `e.state.name` — current state name or None
- `e.state.context` — dict of state context data
- `e.state.set("name", {ctx})` — transition to new state
- `e.state.clear()` — clear state (return to idle)

### Helper methods
- `e.set_workplace(name)` — set scanner's current workplace
- `e.set_employee(name)` — set scanner's current employee

### Return value — use templateData
The scanner has a message template configured in Scanner Configuration that prepends a header with employee name, workplace, and scanned data. Scripts should return `templateData` (not `message`) so the template header is applied:

```python
return {
    "templateData": "line1\nline2\nline3",  # body text, header is prepended automatically
    "target_doctype": "Item",               # optional, for scan log
    "target_document": "ITEM-001",          # optional, for scan log
    "prompt": "Scan next item",             # optional status line
    "image": "...",                          # optional image data
}
```

The template header format (from Scanner Configuration) looks like:
```
К:{employee_name} Рм:{workplace}
>{scanned_data}

```
Then `templateData` content follows.

If you return `message` instead of `templateData`, the raw message is used without the template header.

### Available in script scope
- `frappe` — the Frappe framework module
- `json` — Python json module
- `scripts` — namespace of active Scanner Scripts (accessed as `scripts.script_name.function()`)

### Scanner display constraints
The scanner display has limited size (configured in Scanner Configuration, typically 10 rows x 20 chars). Keep output concise — use short labels, abbreviate where possible.

### Labels should be in Ukrainian
Use Ukrainian labels consistent with `erpnext/translations/uk.csv`.

## 5. Deploy

Use `update_document` with:
- doctype: "Workplace Script"
- name: "<script-name>"
- data: `{"script": "<the python code>"}`

The script takes effect immediately — no deploy or restart needed since it's executed dynamically from the database.

## 6. Testing

Remind the user they can test by scanning a barcode with a scanner configured for the matching workplace, or by calling the API directly:
```
POST /api/method/erpnext.devices.doctype.scanner.scanner_api.handle_scan
{"scanner_key": "...", "data": "..."}
```
