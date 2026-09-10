"""Keep serial numbers barcode-safe.

Code 128 (and every other 1D symbology we print) encodes ASCII only. A single
Cyrillic look-alike character in a serial number — `Т` instead of `T` — makes
barcode generation raise, and the label silently prints without a barcode.

The generated serial numbers are inserted in bulk (`frappe.db.bulk_insert` in
`serial_batch_bundle.py`), so the Serial No controller never runs for them.
Validation therefore happens at every place a serial number is *composed*:
the attribute abbreviation, the template, the item series and the bundle rows.
"""

import re

import frappe
from frappe import _

# a placeholder such as {ATTR:Торгова марка} or ###### names a field, it is not printed
TOKEN_PATTERN = re.compile(r"\{[^{}]*\}")
NON_LATIN_PATTERN = re.compile(r"[^\x20-\x7E]")


def get_non_latin_chars(value):
	return sorted(set(NON_LATIN_PATTERN.findall(value or "")))


def strip_tokens(value):
	return TOKEN_PATTERN.sub("", value or "")


def throw_if_non_latin(value, label, strip_placeholders=False):
	text = strip_tokens(value) if strip_placeholders else value
	chars = get_non_latin_chars(text)
	if not chars:
		return

	frappe.throw(
		_("{0} may contain Latin letters, digits and punctuation only. Remove: {1}").format(
			label, " ".join(f"{c} (U+{ord(c):04X})" for c in chars)
		),
		title=_("Serial Number Must Be Barcode Safe"),
	)


def validate_serial_no(doc, method=None):
	throw_if_non_latin(doc.get("serial_no") or doc.name, _("Serial No"))


def validate_item_serial_series(doc, method=None):
	if doc.get("serial_no_series"):
		throw_if_non_latin(doc.serial_no_series, _("Serial Number Series"), strip_placeholders=True)


def is_used_in_serial_number(attribute_name):
	"""True when the abbreviation of this attribute ends up inside a serial number.

	Abbreviations of attributes used only for item codes (`Штурмовий`, `55А`, …)
	are allowed to stay Cyrillic — they are never encoded in a barcode.
	"""
	if frappe.db.exists("Serial Number Template Component", {"attribute_link": attribute_name}):
		return True

	token = "{ATTR:" + attribute_name + "}"
	return bool(
		frappe.db.exists("Serial Number Template", {"resulting_series": ("like", f"%{token}%")})
		or frappe.db.exists("Item", {"serial_no_series": ("like", f"%{token}%")})
	)


def validate_item_attribute_abbr(doc, method=None):
	if not is_used_in_serial_number(doc.name):
		return

	for row in doc.get("item_attribute_values") or []:
		if row.get("abbr"):
			throw_if_non_latin(
				row.abbr, _("Abbreviation for {0}").format(row.get("attribute_value") or row.idx)
			)


def validate_serial_number_template(doc, method=None):
	if doc.get("resulting_series"):
		throw_if_non_latin(doc.resulting_series, _("Resulting Series"), strip_placeholders=True)

	for row in doc.get("components") or []:
		if row.get("component_type") in ("Literal", "Separator") and row.get("value"):
			throw_if_non_latin(row.value, _("Component {0}").format(row.idx))


def validate_bundle_serial_nos(doc, method=None):
	for row in doc.get("entries") or []:
		if row.get("serial_no"):
			throw_if_non_latin(row.serial_no, _("Serial No"))
