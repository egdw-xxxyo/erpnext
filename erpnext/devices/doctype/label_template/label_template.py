import base64
import io
import json
import os
import re
import subprocess

import frappe
from frappe import _
from frappe.model.document import Document


class LabelTemplate(Document):
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		html_template: DF.Code | None
		label_size: DF.Link | None
		preview_data: DF.Code | None
		reference_doctype: DF.Link | None
		source_field: DF.Literal[""] | None
		template_name: DF.Data | None
		template_type: DF.Literal["From DocType", "Raw Data", "Barcode", "Other"]

	def validate(self):
		if not self.html_template:
			frappe.throw(_("HTML Template is required"))

	def on_trash(self):
		jobs = frappe.get_all("Print Job", filters={"label_template": self.name}, pluck="name")
		for job_name in jobs:
			frappe.delete_doc("Print Job", job_name, force=True, delete_permanently=True)


def _get_label_size_data(label_size_name):
	size = frappe.get_doc("Label Size", label_size_name)
	dpi = 300
	from frappe.utils import flt

	dots_per_mm = dpi / 25.4
	return {
		"width_mm": size.width_mm,
		"height_mm": size.height_mm,
		"width_dots": int(flt(size.width_mm) * dots_per_mm),
		"height_dots": int(flt(size.height_mm) * dots_per_mm),
		"dpi": dpi,
	}


@frappe.whitelist()
def get_template_reference():
	"""Return the Label Template reference (markdown) and published Label Template Examples.

	Single source of truth used by both the UI dialog and the MCP server.
	"""
	ref_path = os.path.join(os.path.dirname(__file__), "REFERENCE.md")
	try:
		with open(ref_path, encoding="utf-8") as f:
			reference_md = f.read()
	except FileNotFoundError:
		reference_md = ""

	from frappe.utils import markdown

	reference_html = markdown(reference_md) if reference_md else ""

	examples = frappe.get_all(
		"Label Template Example",
		filters={"is_published": 1},
		fields=["title", "category", "description_uk", "html_snippet", "notes", "display_order"],
		order_by="category asc, display_order asc, title asc",
	)
	return {
		"reference_md": reference_md,
		"reference_html": reference_html,
		"examples": examples,
	}


@frappe.whitelist()
def get_available_spec_keys(item_code):
	"""Return flattened spec-param keys available as `doc.<key>` for the given item."""
	if not item_code:
		return []
	from erpnext.stock.doctype.item_specification.item_specification import get_spec_for_item

	spec = get_spec_for_item(item_code) or {}
	return [{"key": _spec_param_to_key(name), "param": name} for name in spec.keys()]


@frappe.whitelist()
def get_templates_for_barcode_type(barcode_type):
	"""Return label templates configured for a specific barcode type."""
	return frappe.get_all(
		"Label Template",
		filters={"barcode_type": barcode_type},
		fields=["name as label_template", "label_size"],
	)


@frappe.whitelist()
def render_preview(
	html_template="",
	field_mapping="",
	preview_data="",
	label_size="",
	padding_top_mm=0,
	padding_right_mm=0,
	padding_bottom_mm=0,
	padding_left_mm=0,
	**kwargs,
):
	if not label_size:
		return None

	size = _get_label_size_data(label_size)
	from frappe.utils import flt

	padding_mm = (flt(padding_top_mm), flt(padding_right_mm), flt(padding_bottom_mm), flt(padding_left_mm))

	context = {"frappe": frappe, "_": _}
	if preview_data:
		try:
			doc_dict = frappe._dict(json.loads(preview_data))
		except Exception:
			doc_dict = frappe._dict()
	else:
		doc_dict = frappe._dict()

	if doc_dict.get("item_code") and field_mapping:
		mock_tpl = frappe._dict({"field_mapping": field_mapping})
		resolve_field_mapping(mock_tpl, doc_dict)

	context["doc"] = doc_dict

	if not html_template:
		return None

	html = frappe.render_template(html_template, context)
	html = _process_barcode_tags(html)
	html = _process_attachment_tags(html)
	img_b64 = _html_to_png_base64(html, size["width_dots"], size["height_dots"], padding_mm=padding_mm)
	return {
		"type": "html_image",
		"image_base64": img_b64,
		"html": html,
		**size,
	}


@frappe.whitelist()
def render_job_preview(print_job_name):
	"""Render a preview image for a Print Job using its stored raw_data."""
	job = frappe.get_doc("Print Job", print_job_name)
	template = frappe.get_doc("Label Template", job.label_template)
	size = _get_label_size_data(template.label_size)

	if job.raw_data:
		data = json.loads(job.raw_data)
	else:
		data = {}
	context = {"frappe": frappe, "_": _, "doc": frappe._dict(data)}
	html = frappe.render_template(template.html_template or "", context)
	html = _process_barcode_tags(html)
	html = _process_attachment_tags(html)
	img_b64 = _html_to_png_base64(
		html, size["width_dots"], size["height_dots"], padding_mm=_padding_from_template(template)
	)
	return {
		"type": "html_image",
		"image_base64": img_b64,
		**size,
	}


def _process_barcode_tags(html):
	"""Replace <barcode type="qr|code128|ean13|..." data="..." /> with inline base64 <img> tags."""
	import barcode as barcode_lib
	import qrcode as qrcode_lib
	from barcode.writer import ImageWriter
	from PIL import Image

	def _get_attr(attrs_str, name):
		m = re.search(rf'{name}=["\']([^"\']+)["\']', attrs_str)
		return m.group(1) if m else None

	def _generate_barcode_img(match):
		attrs_str = match.group(1)
		bc_type = _get_attr(attrs_str, "type")
		bc_data = _get_attr(attrs_str, "data")
		bc_size = _get_attr(attrs_str, "size")
		bc_module_width = _get_attr(attrs_str, "module_width")
		bc_module_height = _get_attr(attrs_str, "module_height")

		if not bc_type or not bc_data:
			return match.group(0)

		bc_type = bc_type.lower()

		try:
			buf = io.BytesIO()

			if bc_type == "qr":
				box_size = int(bc_size) if bc_size else 4
				qr = qrcode_lib.QRCode(
					box_size=box_size, border=1, error_correction=qrcode_lib.constants.ERROR_CORRECT_M
				)
				qr.add_data(bc_data)
				qr.make(fit=True)
				img = qr.make_image(fill_color="black", back_color="white")
				img.save(buf, format="PNG")
			else:
				bc_class = barcode_lib.get_barcode_class(bc_type)
				writer = ImageWriter()
				code = bc_class(bc_data, writer=writer)
				opts = {"write_text": False}
				opts["module_width"] = float(bc_module_width) if bc_module_width else 0.2
				opts["module_height"] = float(bc_module_height) if bc_module_height else 8
				code.write(buf, options=opts)

			b64 = base64.b64encode(buf.getvalue()).decode("ascii")

			style_parts = []
			for attr in re.finditer(r'(width|height|style)=["\']([^"\']+)["\']', attrs_str):
				if attr.group(1) == "style":
					style_parts.append(attr.group(2))
				else:
					style_parts.append(f"{attr.group(1)}:{attr.group(2)}")

			style = ";".join(style_parts) if style_parts else ""
			return f'<img src="data:image/png;base64,{b64}" style="{style}" />'
		except Exception:
			return match.group(0)

	return re.sub(r"<barcode\s+(.*?)\s*/?>", _generate_barcode_img, html, flags=re.DOTALL)


def _process_attachment_tags(html):
	"""Replace <attachment name="filename.jpg" /> with inline base64 <img> tags.

	Resolves file from Frappe's file system (public or private).
	Supports width, height, and style attributes.
	"""

	def _get_attr(attrs_str, name):
		m = re.search(rf'{name}=["\']([^"\']+)["\']', attrs_str)
		return m.group(1) if m else None

	def _resolve_attachment(match):
		attrs_str = match.group(1)
		file_name = _get_attr(attrs_str, "name")

		if not file_name:
			return match.group(0)

		try:
			file_doc = frappe.get_value(
				"File", {"file_name": file_name}, ["file_url", "is_private"], as_dict=True
			)
			if not file_doc:
				return match.group(0)

			site_path = frappe.get_site_path()
			if file_doc.is_private:
				file_path = os.path.join(site_path, "private", "files", file_name)
			else:
				file_path = os.path.join(site_path, "public", "files", file_name)

			if not os.path.exists(file_path):
				return match.group(0)

			with open(file_path, "rb") as f:
				file_bytes = f.read()

			ext = file_name.rsplit(".", 1)[-1].lower()
			mime_map = {
				"jpg": "jpeg",
				"jpeg": "jpeg",
				"png": "png",
				"gif": "gif",
				"svg": "svg+xml",
				"webp": "webp",
			}
			mime = mime_map.get(ext, "png")

			b64 = base64.b64encode(file_bytes).decode("ascii")

			style_parts = []
			for attr in re.finditer(r'(width|height|style)=["\']([^"\']+)["\']', attrs_str):
				if attr.group(1) == "style":
					style_parts.append(attr.group(2))
				else:
					style_parts.append(f"{attr.group(1)}:{attr.group(2)}")
			style = ";".join(style_parts) if style_parts else ""

			return f'<img src="data:image/{mime};base64,{b64}" style="{style}" />'
		except Exception:
			return match.group(0)

	return re.sub(r"<attachment\s+(.*?)\s*/?>", _resolve_attachment, html, flags=re.DOTALL)


DPI = 300
PX_PER_MM = DPI / 25.4
UTILITY_MM_STEPS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 25]


def _mm_to_px(mm):
	return round(float(mm) * PX_PER_MM, 3)


def _build_utility_css():
	rules = []
	for n in UTILITY_MM_STEPS:
		px = _mm_to_px(n)
		rules.append(f".pl_{n}mm{{padding-left:{px}px}}")
		rules.append(f".pr_{n}mm{{padding-right:{px}px}}")
		rules.append(f".pt_{n}mm{{padding-top:{px}px}}")
		rules.append(f".pb_{n}mm{{padding-bottom:{px}px}}")
		rules.append(f".lr_{n}mm{{padding-left:{px}px;padding-right:{px}px}}")
		rules.append(f".tb_{n}mm{{padding-top:{px}px;padding-bottom:{px}px}}")
		rules.append(f".p_{n}mm{{padding:{px}px}}")
		rules.append(f".ml_{n}mm{{margin-left:{px}px}}")
		rules.append(f".mr_{n}mm{{margin-right:{px}px}}")
		rules.append(f".mt_{n}mm{{margin-top:{px}px}}")
		rules.append(f".mb_{n}mm{{margin-bottom:{px}px}}")
		rules.append(f".m_{n}mm{{margin:{px}px}}")
		rules.append(f".w_{n}mm{{width:{px}px}}")
		rules.append(f".h_{n}mm{{height:{px}px}}")
	for pct in (25, 50, 75, 100):
		rules.append(f".w_{pct}{{width:{pct}%}}")
		rules.append(f".h_{pct}{{height:{pct}%}}")
	return "\n".join(rules)


def _wrap_html_for_render(html, width_px, height_px, padding_mm=None):
	pt, pr, pb, pl = padding_mm or (0, 0, 0, 0)
	pt_px = _mm_to_px(pt)
	pr_px = _mm_to_px(pr)
	pb_px = _mm_to_px(pb)
	pl_px = _mm_to_px(pl)
	utility_css = _build_utility_css()
	return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{
	width: {width_px}px;
	height: {height_px}px;
	overflow: hidden;
	font-family: Arial, Helvetica, sans-serif;
	-webkit-print-color-adjust: exact;
}}
body {{ position: relative; }}
.label-content {{
	position: absolute;
	top: {pt_px}px;
	right: {pr_px}px;
	bottom: {pb_px}px;
	left: {pl_px}px;
}}
{utility_css}
</style>
</head>
<body><div class="label-content">{html}</div></body>
</html>"""


def _padding_from_template(template_doc):
	if not template_doc:
		return None
	from frappe.utils import flt

	return (
		flt(getattr(template_doc, "padding_top_mm", 0) or 0),
		flt(getattr(template_doc, "padding_right_mm", 0) or 0),
		flt(getattr(template_doc, "padding_bottom_mm", 0) or 0),
		flt(getattr(template_doc, "padding_left_mm", 0) or 0),
	)


def _to_monochrome(png_bytes):
	"""Threshold a rendered PNG to the 1-bit raster the printer actually gets.

	Returns (PIL image in mode "1", 1-bit PNG bytes). wkhtmltoimage emits 32-bit
	RGBA with zlib compression disabled (--quality 100), so its raw output is
	~5.6 MB for a 100x100 mm label at 300 dpi; the same pixels as 1-bit deflate
	are ~20 KB.
	"""
	from PIL import Image

	img = Image.open(io.BytesIO(png_bytes))
	img_bw = img.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

	buf = io.BytesIO()
	img_bw.save(buf, format="PNG", optimize=True, compress_level=9)
	return img_bw, buf.getvalue()


def _html_to_png_base64(html, width_px, height_px, padding_mm=None):
	full_html = _wrap_html_for_render(html, width_px, height_px, padding_mm=padding_mm)
	result = subprocess.run(
		[
			"wkhtmltoimage",
			"--encoding",
			"utf-8",
			"--width",
			str(width_px),
			"--height",
			str(height_px),
			"--quality",
			"100",
			"--format",
			"png",
			"--disable-smart-width",
			"-",
			"-",
		],
		input=full_html.encode("utf-8"),
		capture_output=True,
		timeout=15,
	)
	if result.returncode != 0:
		frappe.log_error(
			title="wkhtmltoimage error",
			message=result.stderr.decode("utf-8", errors="replace"),
		)
		frappe.throw(_("Failed to render HTML to image"))
	_img_bw, png_1bit = _to_monochrome(result.stdout)
	return base64.b64encode(png_1bit).decode("ascii")


def html_to_pcx_bytes(html, width_px, height_px, padding_mm=None):
	pcx_data, _png = html_to_image(html, width_px, height_px, padding_mm=padding_mm)
	return pcx_data


def html_to_image(html, width_px, height_px, padding_mm=None):
	"""Return (pcx_bytes, 1-bit png_bytes) for an HTML label."""
	import time

	log = frappe.logger("label_printer")

	t0 = time.monotonic()
	full_html = _wrap_html_for_render(html, width_px, height_px, padding_mm=padding_mm)
	log.error(f"[TIMING] html_to_image: wrap_html: {(time.monotonic() - t0)*1000:.0f}ms")

	t0 = time.monotonic()
	result = subprocess.run(
		[
			"wkhtmltoimage",
			"--encoding",
			"utf-8",
			"--width",
			str(width_px),
			"--height",
			str(height_px),
			"--quality",
			"100",
			"--format",
			"png",
			"--disable-smart-width",
			"-",
			"-",
		],
		input=full_html.encode("utf-8"),
		capture_output=True,
		timeout=15,
	)
	wk_ms = (time.monotonic() - t0) * 1000
	log.error(
		f"[TIMING] html_to_image: wkhtmltoimage subprocess: {wk_ms:.0f}ms "
		f"(returncode={result.returncode}, stdout={len(result.stdout)}bytes)"
	)
	if result.returncode != 0:
		raise ValueError(f"wkhtmltoimage failed: {result.stderr.decode('utf-8', errors='replace')}")

	png_bytes = result.stdout

	t0 = time.monotonic()
	img_bw, png_1bit = _to_monochrome(png_bytes)

	pcx_buf = io.BytesIO()
	img_bw.save(pcx_buf, format="PCX")
	pil_ms = (time.monotonic() - t0) * 1000
	log.error(
		f"[TIMING] html_to_image: PIL png->pcx conversion: {pil_ms:.0f}ms "
		f"(pcx={pcx_buf.tell()}bytes png={len(png_bytes)}->{len(png_1bit)}bytes)"
	)
	return pcx_buf.getvalue(), png_1bit


def _format_spec_value(p):
	"""Format a spec parameter value with its UOM for label display."""
	raw = p.get("value")
	if not raw and raw != 0:
		return ""
	raw = str(raw).strip()
	if not raw:
		return ""
	try:
		num = float(raw)
		raw = f"{num:g}"
	except (ValueError, TypeError):
		pass
	uom = (p.get("uom") or "").strip()
	if uom:
		return f"{raw}{uom}"
	return raw


def _spec_param_to_key(param_name):
	"""Convert spec parameter name to a flat dict key: lowercase, spaces→underscores, remove apostrophes."""
	return param_name.lower().replace(" ", "_").replace("ʼ", "").replace("'", "")


def _format_spec_for_label(p):
	"""Format a spec parameter dict into a display string for label use.
	Returns the raw value WITHOUT UOM — templates handle units themselves."""
	from erpnext.stock.doctype.item_specification_parameter.formula_utils import parse_number

	raw = str(p.get("value") or "")
	is_formula = raw.startswith("=")
	cv = p.get("calculated_value")
	if cv and cv != 0:
		return f"{float(cv):g}"
	if is_formula:
		return "—"
	if raw:
		num = parse_number(raw)
		return f"{num:g}" if num is not None else raw
	return "—"


def _get_item_attributes(item_code):
	"""Return {attribute name: attribute value} for a variant Item, values stripped."""
	rows = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["attribute", "attribute_value"],
	)
	return {r.attribute: (r.attribute_value or "").strip() for r in rows}


def resolve_field_mapping(template_doc, doc_dict):
	"""Inject all spec params as flat keys into doc_dict, then apply field_mapping overrides.

	For each spec param, a key is created from the param name (lowercase, spaces→_).
	E.g. "Струм заряду" → doc_dict["струм_заряду"] = "8.4А"
	Values passed in by the caller (a real doc field, or preview_data) are never overwritten.
	An explicit field_mapping entry does override an auto-injected spec key, so a template can
	point e.g. "напруга_комірки" at a different parameter than the one that owns that key.
	"""
	item_code = doc_dict.get("item_code")
	spec = None
	attributes = None
	injected = set()

	if item_code:
		from erpnext.stock.doctype.item_specification.item_specification import get_spec_for_item

		raw_spec = get_spec_for_item(item_code) or {}
		spec = {k: frappe._dict(v) for k, v in raw_spec.items()}
		for param_name, p in spec.items():
			key = _spec_param_to_key(param_name)
			if not doc_dict.get(key):
				doc_dict[key] = _format_spec_for_label(p)
				injected.add(key)

	field_mapping = getattr(template_doc, "field_mapping", None)
	if not field_mapping:
		return doc_dict
	try:
		mapping = json.loads(field_mapping)
		for field, cfg in mapping.items():
			if doc_dict.get(field) and field not in injected:
				continue
			source = cfg.get("source")
			if source == "doc":
				val = str(doc_dict.get(cfg["param"]) or "")
				doc_dict[field] = val
			elif source == "spec" and spec:
				p = spec.get(cfg["param"]) or frappe._dict()
				val = _format_spec_for_label(p)
				if cfg.get("transform") == "chemistry":
					val = "Po" if str(p.get("value") or "").startswith("2") else "ion"
				doc_dict[field] = val
			elif source == "attribute" and item_code:
				if attributes is None:
					attributes = _get_item_attributes(item_code)
				doc_dict[field] = attributes.get(cfg["param"], "")
	except Exception:
		pass
	return doc_dict


def render_html_template(template_doc, doc=None, data=None, parent_doc=None):
	import time

	log = frappe.logger("label_printer")
	t_start = time.monotonic()

	context = {"frappe": frappe, "_": _}

	if doc:
		doc_dict = frappe._dict(doc.as_dict() if hasattr(doc, "as_dict") else doc)
	elif data:
		if isinstance(data, str):
			data = json.loads(data)
		doc_dict = frappe._dict(data)
	else:
		doc_dict = frappe._dict()

	t0 = time.monotonic()
	resolve_field_mapping(template_doc, doc_dict)
	log.error(f"[TIMING] render_html_template: resolve_field_mapping: {(time.monotonic() - t0)*1000:.0f}ms")
	context["doc"] = doc_dict

	if parent_doc:
		context["parent"] = parent_doc

	t0 = time.monotonic()
	html = frappe.render_template(template_doc.html_template or "", context)
	log.error(f"[TIMING] render_html_template: jinja2_render: {(time.monotonic() - t0)*1000:.0f}ms")

	t0 = time.monotonic()
	html = _process_barcode_tags(html)
	log.error(f"[TIMING] render_html_template: process_barcodes: {(time.monotonic() - t0)*1000:.0f}ms")

	t0 = time.monotonic()
	html = _process_attachment_tags(html)
	log.error(f"[TIMING] render_html_template: process_attachments: {(time.monotonic() - t0)*1000:.0f}ms")

	log.error(f"[TIMING] render_html_template TOTAL: {(time.monotonic() - t_start)*1000:.0f}ms")
	return html
