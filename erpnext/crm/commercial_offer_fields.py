import frappe
from frappe import _

from erpnext.devices.doctype.label_template.label_template import _format_spec_for_label
from erpnext.stock.doctype.item_specification.item_specification import get_spec_for_item
from erpnext.stock.doctype.item_specification_parameter.formula_utils import (
	_evaluate_formula,
	_get_linked_item_specs,
	extract_formula,
	is_formula,
	parse_number,
)

UNRESOLVED = "—"
MAX_PASSES = 5


def resolve_rows(doc):
	"""Fill default value, final value (`preview`), source summary and an empty `unit` on every field row.
	Returns the rows that end up with no value although they have a source."""
	numeric_cache = {}
	spec_cache = {}

	def numeric(item):
		if item not in numeric_cache:
			numeric_cache[item] = _get_linked_item_specs(item) if item else {}
		return numeric_cache[item]

	def spec(item):
		if item not in spec_cache:
			spec_cache[item] = get_spec_for_item(item) if item else {}
		return spec_cache[item]

	rows = doc.get("spec_fields") or []
	pending = []
	for row in rows:
		item = row.source_item or doc.main_item
		row.override = 1 if _has_custom_value(row) else 0
		row.source_summary = _source_summary(row)
		row.default_value = ""
		if is_formula(row.value):
			pending.append(row)
		elif row.source_field:
			value = frappe.db.get_value("Item", item, row.source_field) if item else None
			row.default_value = (
				"" if value is None else f"{value:g}" if isinstance(value, float) else str(value)
			)
		elif row.source_parameter:
			param = spec(item).get(row.source_parameter)
			if param:
				row.default_value = _display_value(param)
				row.unit = row.unit or param.get("uom") or ""
		else:
			row.default_value = row.value or ""
		_set_final_value(row)

	for _pass in range(MAX_PASSES):
		if not pending:
			break
		still_pending = []
		for row in pending:
			context = dict(numeric(doc.main_item))
			context.update(numeric(row.source_item))
			for other in rows:
				num = parse_number(other.preview)
				if other is not row and other.label and num is not None:
					context[other.label] = num
			try:
				result = _evaluate_formula(extract_formula(row.value), context)
			except (ValueError, ZeroDivisionError, SyntaxError):
				still_pending.append(row)
				continue
			row.default_value = f"{result:g}"
			_set_final_value(row)
		if len(still_pending) == len(pending):
			break
		pending = still_pending

	return [row for row in rows if not row.preview and _has_source(row)]


def _has_custom_value(row):
	return str(row.custom_value if row.custom_value is not None else "").strip() != ""


def _set_final_value(row):
	row.preview = row.custom_value if row.override else row.default_value


def _source_summary(row):
	section = _("Key Capability") if row.section == "Key Capability" else _("Specification")
	item = row.source_item or _("Product")
	if is_formula(row.value):
		source = "ƒ " + extract_formula(row.value)
	elif row.source_field:
		source = f"{item} › {row.source_field}"
	elif row.source_parameter:
		source = f"{item} › {row.source_parameter}"
	else:
		source = _("Text")
	return f"{section} · {source}"


def _has_source(row):
	return bool(row.override or row.source_field or row.source_parameter or is_formula(row.value))


def _display_value(param):
	text = _format_spec_for_label(param)
	return "" if text == UNRESOLVED else text


def throw_if_unresolved(rows):
	if not rows:
		return
	lines = "<br>".join(f"{row.idx}. <b>{frappe.utils.escape_html(row.label or '')}</b>" for row in rows)
	frappe.throw(
		_("These field rows have no value:") + "<br>" + lines, title=_("Unresolved Commercial Offer Fields")
	)


@frappe.whitelist()
def preview_fields(doc):
	doc = frappe.get_doc(frappe.parse_json(doc))
	doc.check_permission("read")
	resolve_rows(doc)
	return [
		{
			"name": row.name,
			"preview": row.preview,
			"default_value": row.default_value,
			"source_summary": row.source_summary,
			"override": row.override,
			"unit": row.unit,
		}
		for row in doc.spec_fields
	]


@frappe.whitelist()
def get_item_parameters(item):
	frappe.has_permission("Item", "read", item, throw=True)
	return [
		{"parameter": name, "uom": param.get("uom") or "", "value": _display_value(param)}
		for name, param in get_spec_for_item(item).items()
	]


def price_in_words(amount, currency):
	from frappe.utils import money_in_words

	if not amount:
		return ""

	lang = frappe.local.lang
	frappe.local.lang = "uk"
	try:
		return money_in_words(amount, currency)
	finally:
		frappe.local.lang = lang
