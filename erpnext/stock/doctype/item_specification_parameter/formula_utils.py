import ast
import operator
import re

import frappe

_OPS = {
	ast.Add: operator.add,
	ast.Sub: operator.sub,
	ast.Mult: operator.mul,
	ast.Div: operator.truediv,
	ast.USub: operator.neg,
}

TOKEN_RE = re.compile(r"\{([^}]+)\}")
NUMERIC_RE = re.compile(r"(\d+(?:\.\d+)?)")


def evaluate_spec_formulas(variant_doc):
	context = _build_context(variant_doc)
	if not context:
		return

	attr_text = _build_text_context(variant_doc)

	for row in variant_doc.get("item_spec_parameters") or []:
		if row.get("formula") and row.get("numeric"):
			try:
				nominal = _evaluate_formula(row.formula, context)
				row.calculated_value = round(nominal, 4)
				tolerance = row.get("tolerance_percent") or 0
				min_val, max_val = _apply_tolerance(nominal, tolerance)
				row.min_value = min_val
				row.max_value = max_val
				row.display_value = _format_display_value(min_val, max_val, row.get("uom"))
			except Exception as e:
				frappe.log_error(
					title=f"Spec Formula Error: {row.get('parameter')}",
					message=f"Formula: {row.formula}\nContext: {context}\nError: {e}",
				)
		elif not row.get("numeric") and not row.get("value") and row.parameter in attr_text:
			row.value = attr_text[row.parameter]
			row.display_value = attr_text[row.parameter]


def _build_text_context(variant_doc):
	"""Build a dict mapping spec parameter names to text values derived from variant attributes.
	E.g. "Конфігурація" → "6S2P", "Тип елемента" → "Molicel P42A"."""
	result = {}
	attributes = variant_doc.get("attributes") or []
	if not attributes:
		return result

	abbrs_by_attr = {}
	for attr in attributes:
		abbr = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr.attribute, "attribute_value": attr.attribute_value},
			"abbr",
		)
		abbrs_by_attr[attr.attribute] = abbr or attr.attribute_value

	s_val = abbrs_by_attr.get("Конфігурація S", "")
	p_val = abbrs_by_attr.get("Конфігурація P", "")
	if s_val or p_val:
		result["Конфігурація"] = f"{s_val}{p_val}"

	for attr in attributes:
		linked_item = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr.attribute, "attribute_value": attr.attribute_value},
			"linked_item",
		)
		if linked_item:
			result["Тип елемента"] = attr.attribute_value
			break

	return result


def _build_context(variant_doc):
	context = {}
	attributes = variant_doc.get("attributes") or []
	if not attributes:
		return context

	for attr in attributes:
		attr_name = attr.attribute
		attr_value = attr.attribute_value

		abbr = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr_name, "attribute_value": attr_value},
			"abbr",
		)
		if abbr:
			num = _extract_numeric_from_abbr(abbr)
			if num is not None:
				context[attr_name] = num

		linked_item = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr_name, "attribute_value": attr_value},
			"linked_item",
		)
		if linked_item:
			specs = _get_linked_item_specs(linked_item)
			for param_name, val in specs.items():
				context[f"{attr_name}.{param_name}"] = val

	return context


def _extract_numeric_from_abbr(abbr):
	match = NUMERIC_RE.search(str(abbr))
	if match:
		return float(match.group(1))
	return None


def _get_linked_item_specs(item_code):
	rows = frappe.get_all(
		"Item Specification Parameter",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["parameter", "numeric", "min_value", "max_value", "value"],
	)
	result = {}
	for r in rows:
		if r.numeric:
			if r.min_value and r.max_value:
				result[r.parameter] = (r.min_value + r.max_value) / 2
			elif r.min_value:
				result[r.parameter] = r.min_value
			elif r.max_value:
				result[r.parameter] = r.max_value
		elif r.value:
			try:
				result[r.parameter] = float(r.value)
			except (ValueError, TypeError):
				pass
	return result


def _evaluate_formula(formula_str, context):
	def replace_token(match):
		key = match.group(1)
		if key not in context:
			raise ValueError(f"Unknown variable: {{{key}}}")
		return str(context[key])

	expr = TOKEN_RE.sub(replace_token, formula_str)
	return _safe_arithmetic(expr)


def _safe_arithmetic(expr_str):
	expr_str = expr_str.strip()
	if not re.match(r"^[\d\s\.\+\-\*/\(\)]+$", expr_str):
		raise ValueError(f"Unsafe expression: {expr_str}")
	tree = ast.parse(expr_str, mode="eval")
	return _eval_node(tree.body)


def _eval_node(node):
	if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
		return float(node.value)
	elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
		return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
	elif isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
		return _OPS[type(node.op)](_eval_node(node.operand))
	else:
		raise ValueError(f"Unsafe node: {ast.dump(node)}")


def _apply_tolerance(nominal, tolerance_percent):
	if not tolerance_percent:
		return (round(nominal, 4), round(nominal, 4))
	delta = abs(nominal) * (tolerance_percent / 100.0)
	return (round(nominal - delta, 4), round(nominal + delta, 4))


def _format_display_value(min_val, max_val, uom):
	def fmt(v):
		if v == int(v):
			return str(int(v))
		return f"{v:.2f}".rstrip("0").rstrip(".")

	uom_str = f" {uom}" if uom else ""
	if min_val == max_val:
		return f"{fmt(min_val)}{uom_str}"
	return f"{fmt(min_val)}-{fmt(max_val)}{uom_str}"
