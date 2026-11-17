"""The designer canvas and the printed label must agree.

The designer draws text in the browser with the font files from erpnext/public/fonts/label/,
kerning off, at font_size_pt * 25.4/72 mm. The printer gets a wkhtmltoimage render of the
compiled layout at 300 dpi. These tests pin the three things that make both the same:
the same font files, the same metrics, the same geometry.
"""

import base64
import hashlib
import io
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.devices.label_layout import FONTS, PX_PER_MM, compile_layout, font_px

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(APP, "public", "fonts", "label")
DESIGNER_JS = os.path.join(APP, "public", "js", "label_designer", "designer.js")
SAMPLES = ["Ver. 25.12.5 (32)", "В коробці 3шт", "AVAVAV To Ty Wa", "БпЛА 1234567890"]


def _designer_font_files():
	src = open(DESIGNER_JS, encoding="utf-8").read()
	block = re.search(r"const LD_FONT_FILES = \{(.*?)\};", src, re.S).group(1)
	return {m[0]: re.findall(r'"([^"]+)"', m[1]) for m in re.findall(r'"([^"]+)":\s*\[([^\]]*)\]', block)}


def _sha(path):
	return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _render(layout, width_mm=100, height_mm=30):
	from PIL import Image, ImageOps

	from erpnext.devices.doctype.label_template.label_template import _html_to_png_base64

	html = frappe.render_template(compile_layout(layout), {"doc": frappe._dict()})
	png = base64.b64decode(
		_html_to_png_base64(html, round(width_mm * PX_PER_MM), round(height_mm * PX_PER_MM))
	)
	img = Image.open(io.BytesIO(png)).convert("L")
	return ImageOps.invert(img).point(lambda x: 255 if x > 127 else 0).getbbox()


def _metric_width(text, size_px, font_file="DejaVuSans"):
	from PIL import ImageFont

	font = ImageFont.truetype(os.path.join(FONT_DIR, f"{font_file}.ttf"), size_px)
	return font.getlength(text, features=["-kern"])


def _text_el(text, x=5, y=5, w=90, h=10, size_pt=10, **style):
	return {
		"type": "text",
		"x": x,
		"y": y,
		"w": w,
		"h": h,
		"text": text,
		"style": {"font_size_pt": size_pt, **style},
	}


class TestLabelRenderParity(FrappeTestCase):
	def test_designer_offers_exactly_the_server_fonts(self):
		files = _designer_font_files()
		self.assertEqual(set(files), set(FONTS))
		for names in files.values():
			for name in names:
				self.assertTrue(os.path.exists(os.path.join(FONT_DIR, f"{name}.ttf")), name)

	def test_bundled_fonts_are_the_files_the_renderer_uses(self):
		if not shutil.which("fc-match"):
			self.skipTest("fontconfig not available")
		for family, (regular, bold) in _designer_font_files().items():
			for name, pattern in ((regular, family), (bold, f"{family}:bold")):
				used = subprocess.run(
					["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True
				).stdout.strip()
				self.assertEqual(
					os.path.basename(used),
					f"{name}.ttf",
					f"wkhtmltoimage renders {pattern!r} with {used}; the designer loads {name}.ttf",
				)
				self.assertEqual(_sha(used), _sha(os.path.join(FONT_DIR, f"{name}.ttf")), name)

	def test_server_text_width_matches_font_metrics(self):
		for size_pt in (7, 8, 10, 14, 24):
			size_px = font_px(size_pt)
			for text in SAMPLES:
				box = _render({"elements": [_text_el(text, size_pt=size_pt, nowrap=1)]})
				ink = box[2] - box[0]
				expected = _metric_width(text, size_px)
				self.assertLessEqual(ink, expected * 1.01 + 2, f"{text!r} @ {size_pt}pt wider on print")
				self.assertGreaterEqual(ink, expected * 0.95, f"{text!r} @ {size_pt}pt narrower on print")

	def test_text_that_fits_the_designer_fits_the_print(self):
		for size_pt in (7, 8, 10, 14, 24):
			size_px = font_px(size_pt)
			line_px = size_px * 1.15
			for text in SAMPLES:
				w_mm = (_metric_width(text, size_px) * 1.01 + 2) / PX_PER_MM
				box = _render({"elements": [_text_el(text, w=w_mm, h=40, size_pt=size_pt)]})
				self.assertLess(
					box[3] - box[1],
					line_px * 1.5,
					f"{text!r} @ {size_pt}pt wrapped on print but fits in designer",
				)

	def test_designer_uses_the_same_font_size_rule(self):
		src = open(DESIGNER_JS, encoding="utf-8").read()
		self.assertIn("Math.round(flt(pt || 10) * (300 / 72))", src)
		self.assertEqual(font_px(10), 42)

	def test_element_position_matches_layout(self):
		box = _render({"elements": [{"type": "rect", "x": 10, "y": 7, "w": 20, "h": 8, "fill": 1}]})
		self.assertAlmostEqual(box[0], 10 * PX_PER_MM, delta=1.5)
		self.assertAlmostEqual(box[1], 7 * PX_PER_MM, delta=1.5)
		self.assertAlmostEqual(box[2] - box[0], 20 * PX_PER_MM, delta=2)
		self.assertAlmostEqual(box[3] - box[1], 8 * PX_PER_MM, delta=2)

	def test_legacy_font_names_render_with_bundled_font(self):
		a = _render({"elements": [_text_el(SAMPLES[0], nowrap=1, font_family="Arial")]})
		b = _render({"elements": [_text_el(SAMPLES[0], nowrap=1, font_family="DejaVu Sans")]})
		self.assertEqual(a, b)
