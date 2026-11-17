"""Visual label layout → Jinja HTML.

A Label Template in "Visual" editor mode stores its design as JSON in `layout_json`.
`compile_layout` turns it into the same body HTML a hand-written template would contain, so
every existing render / print path keeps reading `html_template` unchanged.

Coordinates are millimetres relative to the padded `.label-content` box. The renderer works
at 300 dpi, so everything is emitted in pixels of that canvas (old WebKit in wkhtmltoimage:
no flexbox, tables for vertical alignment).
"""

import json
import re
from html import escape

import frappe
from frappe import _

DPI = 300
PX_PER_MM = DPI / 25.4
PX_PER_PT = DPI / 72

ELEMENT_TYPES = ("text", "field", "input", "image", "barcode", "qr", "table", "line", "rect")
ALIGNS = ("left", "center", "right")
VALIGNS = ("top", "middle", "bottom")
# Only fonts installed in the image (fonts-dejavu-core). The designer loads the very same
# files from erpnext/public/fonts/label/, so the canvas and the printed label share metrics.
FONTS = {
	"DejaVu Sans": "'DejaVu Sans'",
	"DejaVu Serif": "'DejaVu Serif'",
	"DejaVu Sans Mono": "'DejaVu Sans Mono'",
}
FONT_ALIASES = {
	"Arial": "DejaVu Sans",
	"DejaVu Sans Condensed": "DejaVu Sans",
	"Monospace": "DejaVu Sans Mono",
}
DEFAULT_FONT = "DejaVu Sans"
FORMATS = ("", "upper", "date", "datetime", "float:0", "float:1", "float:2", "float:3")
BARCODE_TYPES = ("code128", "code39", "ean13", "ean8", "upca", "isbn13", "gs1_128")
JINJA_EXPR = re.compile(r"(\{\{.*?\}\})", re.DOTALL)


def _px(mm):
	return round(float(mm or 0) * PX_PER_MM, 2)


def _num(value, default=0.0, lo=None, hi=None):
	try:
		n = float(value)
	except (TypeError, ValueError):
		n = default
	if lo is not None:
		n = max(lo, n)
	if hi is not None:
		n = min(hi, n)
	return n


def _key(value, what):
	key = (value or "").strip()
	if not key:
		return ""
	if not key.isidentifier():
		frappe.throw(_("Invalid {0} name: {1}").format(what, key))
	return key


def _text_html(text):
	"""Static text with `{{ ... }}` placeholders: escape the static parts, keep the expressions."""
	out = []
	for part in JINJA_EXPR.split(text or ""):
		if not part:
			continue
		if JINJA_EXPR.fullmatch(part):
			out.append(part)
		else:
			safe = escape(part, quote=False).replace("{", "&#123;").replace("\n", "<br>")
			out.append(safe)
	return "".join(out)


def _value_expr(key, fmt="", scope="doc", attr=False):
	v = f"{scope}.get('{key}')"
	if fmt == "upper":
		body = f"({v} | string).upper()"
	elif fmt == "date":
		body = f"frappe.utils.formatdate({v})"
	elif fmt == "datetime":
		body = f"frappe.utils.format_datetime({v})"
	elif fmt.startswith("float:"):
		body = f"'%.{int(fmt[6:])}f' | format(frappe.utils.flt({v}))"
	else:
		body = v
	if attr:
		clean = "(" + body + ") | string" + "".join(f" | replace('{c}', '')" for c in ('"', "\\'", "<", ">"))
		return f"{{{{ ({clean}) if {v} not in (None, '') else '' }}}}"
	return f"{{{{ ({body}) | e if {v} not in (None, '') else '' }}}}"


def font_px(size_pt):
	"""wkhtmltoimage's WebKit snaps font sizes to whole pixels; emit that size so the designer can match it."""
	return max(1, round(_num(size_pt, 10, 2, 200) * PX_PER_PT))


def font_name(value):
	value = FONT_ALIASES.get(value, value)
	return value if value in FONTS else DEFAULT_FONT


def _style_css(style):
	style = style or {}
	parts = [
		f"font-family:{FONTS[font_name(style.get('font_family'))]}",
		f"font-size:{font_px(style.get('font_size_pt'))}px",
		f"line-height:{_num(style.get('line_height'), 1.15, 0.6, 3)}",
		f"text-align:{style.get('align') if style.get('align') in ALIGNS else 'left'}",
		f"vertical-align:{style.get('valign') if style.get('valign') in VALIGNS else 'top'}",
		f"font-weight:{'bold' if style.get('bold') else 'normal'}",
		f"font-style:{'italic' if style.get('italic') else 'normal'}",
		"color:#fff;background:#000" if style.get("invert") else "color:#000",
		"white-space:nowrap" if style.get("nowrap") else "word-wrap:break-word",
	]
	if style.get("underline"):
		parts.append("text-decoration:underline")
	return ";".join(parts)


def _border_css(style):
	b = _num((style or {}).get("border_mm"), 0, 0, 10)
	return f"border:{_px(b)}px solid #000;" if b else ""


def _cell_box(inner, style, extra_td=""):
	return (
		'<table style="width:100%;height:100%;border-collapse:collapse;table-layout:fixed">'
		f'<tr><td style="padding:0;{_style_css(style)};{extra_td}">{inner}</td></tr></table>'
	)


def _barcode_data(el):
	source = el.get("source") or "field"
	if source == "text":
		return _text_html(el.get("data") or "").replace('"', "&#34;")
	key = _key(el.get("field"), _("field"))
	return _value_expr(key, attr=True) if key else ""


def _barcode_html(el):
	data = _barcode_data(el)
	if not data:
		return ""
	style = el.get("style") or {}
	if el["type"] == "qr":
		size = int(_num(el.get("module_size"), 4, 1, 40))
		side = _px(min(_num(el.get("w"), 10, 0.1), _num(el.get("h"), 10, 0.1)))
		return _cell_box(
			f'<barcode type="qr" data="{data}" size="{size}" style="width:{side}px;height:{side}px" />',
			{**style, "align": "center", "valign": "middle"},
		)
	bc_type = el.get("barcode_type") if el.get("barcode_type") in BARCODE_TYPES else "code128"
	module_width = _num(el.get("module_width"), 0.2, 0.05, 2)
	box_w, box_h = _px(_num(el.get("w"), 10, 0.1)), _px(_num(el.get("h"), 5, 0.1))
	text_h = 0
	if el.get("show_text"):
		text_h = round(min(_num(style.get("font_size_pt"), 8, 2, 200) * PX_PER_PT * 1.3, box_h / 2), 2)
	img = (
		f'<barcode type="{bc_type}" data="{data}" module_width="{module_width}" '
		f'module_height="8" quiet_zone="1" style="display:block;width:{box_w}px;height:{round(box_h - text_h, 2)}px" />'
	)
	if not text_h:
		return img
	text_style = {**style, "align": "center", "valign": "top", "nowrap": 1, "line_height": 1}
	return f'{img}<div style="height:{text_h}px;overflow:hidden;{_style_css(text_style)}">{data}</div>'


def _image_html(el):
	file_name = (el.get("file") or "").strip()
	if not file_name or re.search(r"[\"'<>]", file_name):
		return ""
	if el.get("fit") == "stretch":
		return f'<attachment name="{file_name}" style="width:100%;height:100%;display:block" />'
	return _cell_box(
		f'<attachment name="{file_name}" style="max-width:100%;max-height:100%" />',
		{"align": "center", "valign": "middle"},
	)


def _table_html(el):
	style = el.get("style") or {}
	cols = [_num(c, 10, 0.5, 1000) for c in (el.get("cols") or [])] or [10]
	rows = el.get("rows") or []
	loop = _key(el.get("loop"), _("table"))
	border = _num(style.get("border_mm"), 0.3, 0, 10)
	border_css = f"border:{_px(border)}px solid #000;" if border else ""
	pad = _px(_num(el.get("cell_padding_mm"), 0.5, 0, 10))
	total = sum(cols)

	colgroup = "".join(f'<col style="width:{round(c / total * 100, 3)}%">' for c in cols)

	def row_html(row):
		cells = []
		for cell in (row.get("cells") or [])[: len(cols)]:
			cell = cell or {}
			span = int(_num(cell.get("colspan"), 1, 1, len(cols)))
			cstyle = {**style, **{k: v for k, v in cell.items() if k in ("bold", "align", "italic")}}
			cells.append(
				f'<td colspan="{span}" style="{border_css}padding:{pad}px;overflow:hidden;'
				f'{_style_css(cstyle)}">{_text_html(cell.get("text") or "")}</td>'
			)
		h = _num(row.get("h"), 0, 0, 1000)
		h_css = f' style="height:{_px(h)}px"' if h else ""
		return f"<tr{h_css}>{''.join(cells)}</tr>"

	if loop and len(rows) >= 2:
		header = "".join(row_html(r) for r in rows[:-1])
		body = f"{{% for row in (doc.get('{loop}') or []) %}}{row_html(rows[-1])}{{% endfor %}}"
		inner = header + body
	else:
		inner = "".join(row_html(r) for r in rows)

	return (
		'<table style="width:100%;border-collapse:collapse;table-layout:fixed">'
		f"<colgroup>{colgroup}</colgroup>{inner}</table>"
	)


def _element_inner(el):
	t = el["type"]
	style = el.get("style") or {}
	if t == "text":
		return _cell_box(_text_html(el.get("text") or ""), style)
	if t in ("field", "input"):
		key = _key(el.get("field") if t == "field" else el.get("input"), _("field"))
		if not key:
			return ""
		fmt = el.get("format") if el.get("format") in FORMATS else ""
		value = _value_expr(key, fmt)
		return _cell_box(
			_text_html(el.get("prefix") or "") + value + _text_html(el.get("suffix") or ""), style
		)
	if t == "image":
		return _image_html(el)
	if t in ("barcode", "qr"):
		return _barcode_html(el)
	if t == "table":
		return _table_html(el)
	if t == "line":
		return '<div style="width:100%;height:100%;background:#000"></div>'
	if t == "rect":
		fill = "background:#000;" if el.get("fill") else ""
		b = _px(_num(style.get("border_mm"), 0.3, 0, 10))
		radius = _px(_num(el.get("radius_mm"), 0, 0, 50))
		return (
			f'<div style="width:100%;height:100%;{fill}border:{b}px solid #000;'
			f'border-radius:{radius}px;-webkit-border-radius:{radius}px"></div>'
		)
	return ""


def _element_html(el):
	x, y = _num(el.get("x")), _num(el.get("y"))
	w, h = _num(el.get("w"), 10, 0.1), _num(el.get("h"), 5, 0.1)
	rotate = int(_num(el.get("rotate"), 0)) % 360
	if rotate not in (0, 90, 180, 270):
		rotate = 0
	box = (
		f"position:absolute;left:{_px(x)}px;top:{_px(y)}px;width:{_px(w)}px;height:{_px(h)}px;"
		"overflow:hidden;"
	)
	if el["type"] not in ("table", "rect"):
		box += _border_css(el.get("style"))
	if rotate:
		box += f"-webkit-transform:rotate({rotate}deg);transform:rotate({rotate}deg);"
	return f'<div class="le le-{el["type"]}" style="{box}">{_element_inner(el)}</div>'


def parse_layout(layout):
	if not layout:
		return {"v": 1, "elements": []}
	if isinstance(layout, str):
		try:
			layout = json.loads(layout)
		except ValueError:
			frappe.throw(_("Layout is not valid JSON"))
	if not isinstance(layout, dict) or not isinstance(layout.get("elements", []), list):
		frappe.throw(_("Layout must be an object with an elements list"))
	for el in layout.get("elements") or []:
		if not isinstance(el, dict) or el.get("type") not in ELEMENT_TYPES:
			frappe.throw(_("Unknown layout element: {0}").format((el or {}).get("type")))
	return layout


def compile_layout(layout):
	layout = parse_layout(layout)
	elements = layout.get("elements") or []
	html = "\n".join(_element_html(el) for el in elements if not el.get("hidden"))
	return f"<!-- visual-layout v{int(_num(layout.get('v'), 1))} -->\n{html}"


@frappe.whitelist()
def compile_layout_api(layout):
	if not frappe.has_permission("Label Template", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return compile_layout(layout)
