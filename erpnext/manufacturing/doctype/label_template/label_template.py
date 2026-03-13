import base64
import io
import json
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
		template_type: DF.Literal["EZPL", "HTML"]
		zpl_template: DF.Code | None

	def validate(self):
		if self.template_type == "EZPL" and not self.zpl_template:
			frappe.throw(_("EZPL Template is required when Template Type is EZPL"))
		if self.template_type == "HTML" and not self.html_template:
			frappe.throw(_("HTML Template is required when Template Type is HTML"))

	def on_trash(self):
		jobs = frappe.get_all("Print Job", filters={"label_template": self.name}, pluck="name")
		for job_name in jobs:
			frappe.delete_doc("Print Job", job_name, force=True, delete_permanently=True)


def render_ezpl(template_doc, doc=None, data=None):
	context = {"frappe": frappe, "_": _}

	if doc:
		context["doc"] = doc
	elif data:
		if isinstance(data, str):
			data = json.loads(data)
		context["doc"] = frappe._dict(data)
	else:
		context["doc"] = frappe._dict()

	return frappe.render_template(template_doc.zpl_template, context)


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


def _parse_ezpl_to_elements(ezpl_text):
	elements = []
	for line in ezpl_text.split("\n"):
		line = line.strip("\r\n ")
		if not line:
			continue

		# Text: AA,x,y,h_mult,v_mult,rot,rev,text  (font A-Z)
		m = re.match(r"^A([A-Za-z0-9]),(\d+),(\d+),(\d+),(\d+),\d+,\d+,(.+)$", line)
		if m:
			elements.append({
				"type": "text",
				"font": m.group(1),
				"x": int(m.group(2)),
				"y": int(m.group(3)),
				"h_mult": int(m.group(4)),
				"v_mult": int(m.group(5)),
				"text": m.group(6),
			})
			continue

		# Barcode 128: BA,x,y,narrow,wide,height,rot,rev,text
		m = re.match(r"^B([A-Za-z0-9]),(\d+),(\d+),(\d+),(\d+),(\d+),\d+,\d+,(.+)$", line)
		if m:
			elements.append({
				"type": "barcode",
				"subtype": m.group(1),
				"x": int(m.group(2)),
				"y": int(m.group(3)),
				"narrow": int(m.group(4)),
				"wide": int(m.group(5)),
				"height": int(m.group(6)),
				"text": m.group(7),
			})
			continue

		# QR code: BQ,x,y,model,module_size,error_level,data
		m = re.match(r"^BQ,(\d+),(\d+),\d+,(\d+),.+?,(.+)$", line)
		if m:
			elements.append({
				"type": "qrcode",
				"x": int(m.group(1)),
				"y": int(m.group(2)),
				"module_size": int(m.group(3)),
				"text": m.group(4),
			})
			continue

		# Line: LO,x,y,length,thickness
		m = re.match(r"^LO,(\d+),(\d+),(\d+),(\d+)", line)
		if m:
			elements.append({
				"type": "line",
				"x": int(m.group(1)),
				"y": int(m.group(2)),
				"length": int(m.group(3)),
				"thickness": int(m.group(4)),
			})
			continue

		# Box: X,x,y,w,h,thickness
		m = re.match(r"^X,(\d+),(\d+),(\d+),(\d+),(\d+)", line)
		if m:
			elements.append({
				"type": "box",
				"x": int(m.group(1)),
				"y": int(m.group(2)),
				"box_w": int(m.group(3)),
				"box_h": int(m.group(4)),
				"thickness": int(m.group(5)),
			})
			continue

	return elements


@frappe.whitelist()
def render_preview(template_type, zpl_template="", html_template="", preview_data="", label_size=""):
	if not label_size:
		return None

	size = _get_label_size_data(label_size)

	context = {"frappe": frappe, "_": _}
	if preview_data:
		try:
			context["doc"] = frappe._dict(json.loads(preview_data))
		except Exception:
			context["doc"] = frappe._dict()
	else:
		context["doc"] = frappe._dict()

	if template_type == "EZPL":
		if not zpl_template:
			return None

		rendered = frappe.render_template(zpl_template, context)
		elements = _parse_ezpl_to_elements(rendered)

		return {
			"type": "ezpl_parsed",
			"rendered": rendered,
			"elements": elements,
			**size,
		}

	elif template_type == "HTML":
		if not html_template:
			return None

		html = frappe.render_template(html_template, context)
		html = _process_barcode_tags(html)
		img_b64 = _html_to_png_base64(html, size["width_dots"], size["height_dots"])
		return {
			"type": "html_image",
			"image_base64": img_b64,
			"html": html,
			**size,
		}

	return None


@frappe.whitelist()
def preview_zpl(template_name):
	template = frappe.get_doc("Label Template", template_name)
	data = None
	if template.preview_data:
		data = json.loads(template.preview_data)
	return render_ezpl(template, data=data)


def _process_barcode_tags(html):
	"""Replace <barcode type="qr|code128|ean13|..." data="..." /> with inline base64 <img> tags."""
	import qrcode as qrcode_lib
	import barcode as barcode_lib
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
				qr = qrcode_lib.QRCode(box_size=box_size, border=1, error_correction=qrcode_lib.constants.ERROR_CORRECT_M)
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


def _wrap_html_for_render(html, width_px, height_px):
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
</style>
</head>
<body>{html}</body>
</html>"""


def _html_to_png_base64(html, width_px, height_px):
	full_html = _wrap_html_for_render(html, width_px, height_px)
	result = subprocess.run(
		[
			"wkhtmltoimage",
			"--encoding", "utf-8",
			"--width", str(width_px),
			"--height", str(height_px),
			"--quality", "100",
			"--format", "png",
			"--disable-smart-width",
			"-", "-",
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
	return base64.b64encode(result.stdout).decode("ascii")


def html_to_pcx_bytes(html, width_px, height_px):
	pcx_data, _png = html_to_image(html, width_px, height_px)
	return pcx_data


def html_to_image(html, width_px, height_px):
	"""Return (pcx_bytes, png_bytes) for an HTML label."""
	from PIL import Image

	full_html = _wrap_html_for_render(html, width_px, height_px)
	result = subprocess.run(
		[
			"wkhtmltoimage",
			"--encoding", "utf-8",
			"--width", str(width_px),
			"--height", str(height_px),
			"--quality", "100",
			"--format", "png",
			"--disable-smart-width",
			"-", "-",
		],
		input=full_html.encode("utf-8"),
		capture_output=True,
		timeout=15,
	)
	if result.returncode != 0:
		raise ValueError(f"wkhtmltoimage failed: {result.stderr.decode('utf-8', errors='replace')}")

	png_bytes = result.stdout

	img = Image.open(io.BytesIO(png_bytes))
	img_bw = img.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

	pcx_buf = io.BytesIO()
	img_bw.save(pcx_buf, format="PCX")
	return pcx_buf.getvalue(), png_bytes


def render_html_template(template_doc, doc=None, data=None, parent_doc=None):
	context = {"frappe": frappe, "_": _}

	if doc:
		context["doc"] = doc
	elif data:
		if isinstance(data, str):
			data = json.loads(data)
		context["doc"] = frappe._dict(data)
	else:
		context["doc"] = frappe._dict()

	if parent_doc:
		context["parent"] = parent_doc

	html = frappe.render_template(template_doc.html_template or "", context)
	return _process_barcode_tags(html)
