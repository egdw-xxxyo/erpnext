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


def is_formula(value):
	return bool(value) and str(value).startswith("=")


def extract_formula(value):
	if is_formula(value):
		return str(value)[1:].strip()
	return str(value) if value else ""


def evaluate_spec_formulas(variant_doc):
	context = _build_context(variant_doc)
	attr_text = _build_text_context(variant_doc)
	jinja_ctx = _build_jinja_context(variant_doc)

	for row in variant_doc.get("item_spec_parameters") or []:
		if is_formula(row.get("value")):
			expr = extract_formula(row.value)
			if "{{" in expr:
				try:
					rendered = frappe.render_template(expr, jinja_ctx)
					row.display_value = rendered.strip()
				except Exception as e:
					frappe.log_error(
						title=f"Spec Jinja Error: {row.get('parameter')}",
						message=f"Formula: {row.value}\nError: {e}",
					)
				continue
			if not context:
				continue
			try:
				nominal = _evaluate_formula(expr, context)
				row.calculated_value = round(nominal, 4)
			except Exception as e:
				frappe.log_error(
					title=f"Spec Formula Error: {row.get('parameter')}",
					message=f"Formula: {row.value}\nContext: {context}\nError: {e}",
				)
		elif not row.get("value") and row.parameter in attr_text:
			row.value = attr_text[row.parameter]


def _build_jinja_context(variant_doc):
	attributes = variant_doc.get("attributes") or []

	abbr_map = {}
	for attr in attributes:
		abbr = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr.attribute, "attribute_value": attr.attribute_value},
			"abbr",
		)
		abbr_map[attr.attribute] = abbr or attr.attribute_value

	def abbr(attr_name):
		return abbr_map.get(attr_name, "")

	def spec(attr_name, param):
		attr = next((a for a in attributes if a.attribute == attr_name), None)
		if not attr:
			return ""
		linked_item = frappe.db.get_value(
			"Item Attribute Value",
			{"parent": attr_name, "attribute_value": attr.attribute_value},
			"linked_item",
		)
		if not linked_item:
			return ""
		return (
			frappe.db.get_value(
				"Item Specification Parameter",
				{"parent": linked_item, "parenttype": "Item", "parameter": param},
				"value",
			)
			or ""
		)

	return {
		"doc": variant_doc,
		"abbr": abbr,
		"spec": spec,
	}


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
		fields=["parameter", "value", "calculated_value"],
	)
	result = {}
	for r in rows:
		if r.calculated_value:
			result[r.parameter] = float(r.calculated_value)
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
	if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
		return float(node.value)
	elif isinstance(node, ast.BinOp) and type(node.op) in _OPS:
		return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
	elif isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
		return _OPS[type(node.op)](_eval_node(node.operand))
	else:
		raise ValueError(f"Unsafe node: {ast.dump(node)}")
