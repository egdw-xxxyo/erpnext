# Label Template Reference

Single source of truth for the Label Template HTML rendering reference.
Read by both the UI **Template Reference** dialog and the MCP `get_label_template_reference` tool.

## Rendering pipeline

1. Jinja2 renders `html_template` with `doc` (and optionally `parent`) context.
2. Custom tags `<barcode>` and `<attachment>` are replaced with inline base64 `<img>` tags.
3. The result is wrapped in `<body><div class="label-content">...</div></body>` where:
   - `body` has fixed `width × height` in pixels (300 DPI).
   - `.label-content` is `position:absolute` inset by the four `padding_*_mm` template fields, providing a positioned containing block for absolute children.
4. wkhtmltoimage rasterizes the HTML to PNG, then PIL converts to 1-bit PCX for the printer.

## Padding fields

The four `Padding (mm)` fields on the Label Template apply to the `.label-content` wrapper:

| Field | Effect |
|---|---|
| `padding_top_mm` | Top inset of `.label-content` |
| `padding_right_mm` | Right inset |
| `padding_bottom_mm` | Bottom inset |
| `padding_left_mm` | Left inset |

Children with `position:absolute; top:0; left:0; width:100%; height:100%` fill the padded area, **not** the full label.

## Jinja context

| Variable | Description |
|---|---|
| `{{ doc.fieldname }}` | Field from the source document (e.g. `doc.serial_no`, `doc.item_code`, `doc.item_name`). |
| `{{ parent.fieldname }}` | Field from the parent document (when source is a child table). |
| `{{ frappe.format(value, df) }}` | Frappe value formatter. |
| `{{ _("text") }}` | Translation function. |

## Custom tags

### `<barcode>` — inline barcode/QR image

| Attribute | Required | Description |
|---|---|---|
| `type` | yes | `code128`, `ean13`, `qr`, etc. |
| `data` | yes | Encoded data (Jinja-aware: `{{ doc.serial_no }}`). |
| `module_width` | no | Bar width in mm (default `0.2`). |
| `module_height` | no | Bar height in mm (default `8`). |
| `size` | no | QR module size (default `4`, only for `type="qr"`). |
| `width`, `height`, `style` | no | CSS for the generated `<img>`. |

```html
<barcode type="code128" data="{{ doc.serial_no }}"
  module_width="0.4" module_height="6" style="width:100%;height:auto" />
```

### `<attachment>` — inline image from a Frappe File

Resolves `name` against Frappe's File system (public or private) and inlines as base64.

| Attribute | Required | Description |
|---|---|---|
| `name` | yes | Filename as stored in File Manager (e.g. `logo.png`). |
| `width`, `height`, `style` | no | CSS for the generated `<img>`. |

```html
<attachment name="logo.png" style="width:30px;height:auto" />
```

## Utility CSS classes

Generated automatically and injected into every rendered label. Conversion at 300 DPI: **1 mm = 11.811 px**.

Steps in mm: `1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25`.

| Class pattern | Effect |
|---|---|
| `pl_Nmm` / `pr_Nmm` / `pt_Nmm` / `pb_Nmm` | Padding on a single side |
| `lr_Nmm` / `tb_Nmm` | Padding left+right / top+bottom |
| `p_Nmm` | Padding on all sides |
| `ml_Nmm` / `mr_Nmm` / `mt_Nmm` / `mb_Nmm` / `m_Nmm` | Margin (per side or all) |
| `w_Nmm` / `h_Nmm` | Fixed width / height in mm |
| `w_25` / `w_50` / `w_75` / `w_100` | Width as percentage |
| `h_25` / `h_50` / `h_75` / `h_100` | Height as percentage |

## Layout guidance

wkhtmltoimage is based on an old WebKit and does **not** support flexbox reliably. Use `<table>` for layout:

| Technique | Notes |
|---|---|
| Root `<table style="width:100%;height:100%">` | Stretches across the full label area. |
| `height:1%` on a row | Row shrinks to content. |
| One row without `height` | Absorbs remaining vertical space. |
| `vertical-align:bottom` | Pins content to the bottom of a cell. |
| Nested `<table>` | Use for horizontal grouping (e.g. logo + text + logo). |

## Authoring tips

- Keep the HTML body content only — the `<html>`, `<head>`, `<body>` wrapper and the `.label-content` div are added automatically.
- For absolute positioning, prefer `width:100%;height:100%` on the child and let `.label-content` size it.
- Test with the **Preview** panel after every change; padding fields trigger a fresh render.
- Use the `Label Template Example` DocType to register reusable snippets — they appear in this dialog under **Приклади** and are also surfaced to the MCP `get_label_template_reference` tool.
