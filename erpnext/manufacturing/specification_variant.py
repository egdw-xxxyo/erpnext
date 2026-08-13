import copy
import json
import re

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

PARENT_DOCTYPE = "Specification"
ATTRIBUTE_DOCTYPE = "Item Attribute"
ATTRIBUTE_VALUE_DOCTYPE = "Item Attribute Value"
VARIANT_ATTRIBUTE_DOCTYPE = "Specification Variant Attribute"
VARIANT_SETTINGS_DOCTYPE = "Specification Variant Settings"
VARIANT_FIELD_DOCTYPE = "Specification Variant Field"


class SpecificationVariantExistsError(frappe.ValidationError):
	pass


class InvalidSpecificationAttributeValueError(frappe.ValidationError):
	pass


@frappe.whitelist()
def get_variant(template, args=None, variant=None):
	"""Find an existing variant of `template` that matches `args` exactly."""
	if isinstance(args, str):
		args = json.loads(args)

	if not args:
		frappe.throw(_("Please specify at least one attribute in the Attributes table"))

	return find_variant(template, args, variant)


def validate_variant_attributes(spec, args=None):
	if isinstance(spec, str):
		spec = frappe.get_doc(PARENT_DOCTYPE, spec)

	if not args:
		args = {d.attribute.lower(): d.attribute_value for d in spec.attributes}

	attribute_values, numeric_values = get_attribute_values(spec)

	for attribute, value in args.items():
		if not value:
			continue

		if attribute.lower() in numeric_values:
			numeric_attribute = numeric_values[attribute.lower()]
			validate_is_incremental(numeric_attribute, attribute, value, spec.name)
		else:
			attributes_list = attribute_values.get(attribute.lower(), [])
			validate_attribute_value(attributes_list, attribute, value, spec.name, from_variant=True)


def validate_is_incremental(numeric_attribute, attribute, value, spec):
	from_range = numeric_attribute.from_range
	to_range = numeric_attribute.to_range
	increment = numeric_attribute.increment

	if increment == 0:
		frappe.throw(_("Increment for Attribute {0} cannot be 0").format(attribute))

	is_in_range = from_range <= flt(value) <= to_range
	precision = max(len(cstr(v).split(".")[-1].rstrip("0")) for v in (value, increment))
	remainder = flt((flt(value) - from_range) % increment, precision)
	is_incremental = remainder == 0 or remainder == increment

	if not (is_in_range and is_incremental):
		frappe.throw(
			_(
				"Value for Attribute {0} must be within the range of {1} to {2} in the increments of {3} for {4}"
			).format(attribute, from_range, to_range, increment, spec),
			InvalidSpecificationAttributeValueError,
			title=_("Invalid Attribute"),
		)


def validate_attribute_value(attributes_list, attribute, attribute_value, spec, from_variant=True):
	allow_rename_attribute_value = frappe.db.get_single_value(
		VARIANT_SETTINGS_DOCTYPE, "allow_rename_attribute_value"
	)
	if allow_rename_attribute_value:
		return

	if attribute_value not in attributes_list:
		if from_variant:
			frappe.throw(
				_("{0} is not a valid Value for Attribute {1} of {2}.").format(
					frappe.bold(attribute_value), frappe.bold(attribute), frappe.bold(spec)
				),
				InvalidSpecificationAttributeValueError,
				title=_("Invalid Value"),
			)
		else:
			msg = _("The value {0} is already assigned to an existing {1}.").format(
				frappe.bold(attribute_value), frappe.bold(spec)
			)
			msg += "<br>" + _(
				"To still proceed with editing this Attribute Value, enable {0} in Specification Variant Settings."
			).format(frappe.bold(_("Allow Rename Attribute Value")))

			frappe.throw(msg, InvalidSpecificationAttributeValueError, title=_("Edit Not Allowed"))


def get_attribute_values(spec):
	if not frappe.flags.specification_attribute_values:
		attribute_values = {}
		numeric_values = {}
		for t in frappe.get_all(ATTRIBUTE_VALUE_DOCTYPE, fields=["parent", "attribute_value"]):
			attribute_values.setdefault(t.parent.lower(), []).append(t.attribute_value)

		for t in frappe.get_all(
			VARIANT_ATTRIBUTE_DOCTYPE,
			fields=["attribute", "from_range", "to_range", "increment"],
			filters={"numeric_values": 1, "parent": spec.variant_of},
		):
			numeric_values[t.attribute.lower()] = t

		frappe.flags.specification_attribute_values = attribute_values
		frappe.flags.specification_numeric_values = numeric_values

	return frappe.flags.specification_attribute_values, frappe.flags.specification_numeric_values


def find_variant(template, args, variant_code=None):
	possible = [i for i in _get_codes_by_attributes(args, template) if i != variant_code]

	for variant_name in possible:
		variant = frappe.get_doc(PARENT_DOCTYPE, variant_name)

		if len(args.keys()) == len(variant.get("attributes")):
			match_count = 0
			for attribute, value in args.items():
				for row in variant.attributes:
					if row.attribute == attribute and row.attribute_value == cstr(value):
						match_count += 1
						break
			if match_count == len(args.keys()):
				return variant.name


def _get_codes_by_attributes(attribute_filters, template_name):
	"""Return Specification names whose attribute rows match every key in filters."""
	matched_sets = []
	for attribute, values in attribute_filters.items():
		if not isinstance(values, list):
			values = [values]
		if not values:
			continue

		wheres = []
		params = []
		for v in values:
			wheres.append("(attribute = %s and attribute_value = %s)")
			params += [attribute, v]
		params.append(template_name)

		rows = frappe.db.sql(
			f"""
			SELECT t1.parent
			FROM `tab{VARIANT_ATTRIBUTE_DOCTYPE}` t1
			WHERE ({' or '.join(wheres)})
				AND EXISTS (
					SELECT 1 FROM `tab{PARENT_DOCTYPE}` t2
					WHERE t2.name = t1.parent AND t2.variant_of = %s
				)
			GROUP BY t1.parent
			""",
			params,
		)
		matched_sets.append({r[0] for r in rows})

	if not matched_sets:
		return []
	return list(set.intersection(*matched_sets))


@frappe.whitelist()
def create_variant(spec, args):
	if isinstance(args, str):
		args = json.loads(args)

	template = frappe.get_doc(PARENT_DOCTYPE, spec)
	variant = frappe.new_doc(PARENT_DOCTYPE)
	variant_attributes = []

	for d in template.attributes:
		variant_attributes.append({"attribute": d.attribute, "attribute_value": args.get(d.attribute)})

	variant.set("attributes", variant_attributes)
	copy_attributes_to_variant(template, variant)
	make_variant_code(template.name, template.specification_name, variant)

	return variant


@frappe.whitelist()
def enqueue_multiple_variant_creation(spec, args):
	if isinstance(args, str):
		variants = json.loads(args)
	else:
		variants = args

	total = 1
	for key in variants:
		total *= len(variants[key])
	if total >= 600:
		frappe.throw(_("Please do not create more than 500 specifications at a time"))
		return
	if total < 10:
		return create_multiple_variants(spec, variants)
	else:
		frappe.enqueue(
			"erpnext.manufacturing.specification_variant.create_multiple_variants",
			spec=spec,
			args=variants,
			now=frappe.flags.in_test,
		)
		return "queued"


def create_multiple_variants(spec, args):
	count = 0
	if isinstance(args, str):
		args = json.loads(args)

	args_set = generate_keyed_value_combinations(args)

	for attribute_values in args_set:
		if not get_variant(spec, args=attribute_values):
			variant = create_variant(spec, attribute_values)
			variant.save()
			count += 1

	return count


def generate_keyed_value_combinations(args):
	if not args:
		return []

	key_value_lists = [[(key, val) for val in args[key]] for key in args.keys()]
	results = key_value_lists.pop(0)
	results = [{d[0]: d[1]} for d in results]

	for l in key_value_lists:
		new_results = []
		for res in results:
			for key_val in l:
				obj = copy.deepcopy(res)
				obj[key_val[0]] = key_val[1]
				new_results.append(obj)
		results = new_results

	return results


def copy_attributes_to_variant(template, variant):
	exclude_fields = {
		"naming_series",
		"specification_code",
		"specification_name",
		"variant_of",
		"has_variants",
	}

	allow_fields = [d.field_name for d in frappe.get_all(VARIANT_FIELD_DOCTYPE, fields=["field_name"])]

	for field in template.meta.fields:
		if (field.reqd or field.fieldname in allow_fields) and field.fieldname not in exclude_fields:
			if variant.get(field.fieldname) != template.get(field.fieldname):
				if field.fieldtype == "Table":
					variant.set(field.fieldname, [])
					for d in template.get(field.fieldname):
						row = copy.deepcopy(d)
						if row.get("name"):
							row.name = None
						variant.append(field.fieldname, row)
				else:
					variant.set(field.fieldname, template.get(field.fieldname))

	variant.variant_of = template.name


def make_code_from_pattern(pattern, attributes, variant=None):
	"""Resolve `{AttributeName}` placeholders against rows with attribute/attribute_value.
	Prefers `short_name` from Specification Attribute Value, falls back to `abbr`, then raw value.

	With a `variant` doc two more placeholder families resolve: `{ORDINAL}` (optionally
	`{ORDINAL:4}`) for its catalog position, and `{RoleName}` for the name of the child
	specification sitting in that Specification Component role.
	"""
	result = pattern
	if variant is not None:
		result = _resolve_ordinal_placeholder(result, variant)
		result = _resolve_role_placeholders(result, variant)
	for attr in attributes or []:
		placeholder = "{" + attr.attribute + "}"
		if placeholder not in result:
			continue

		row = frappe.db.get_value(
			ATTRIBUTE_VALUE_DOCTYPE,
			{"parent": attr.attribute, "attribute_value": attr.attribute_value},
			["display_name", "short_name", "abbr"],
			as_dict=True,
		)
		display = (row.display_name or row.short_name or row.abbr) if row else cstr(attr.attribute_value)
		result = result.replace(placeholder, display)
	# An unresolved placeholder or an empty ordinal leaves gaps behind.
	return " ".join(result.split())


def _resolve_ordinal_placeholder(pattern, variant):
	ordinal = variant.get("ordinal")
	for match in set(re.findall(r"\{ORDINAL(?::(\d+))?\}", pattern)):
		digits = int(match) if match else 2
		placeholder = "{ORDINAL:" + match + "}" if match else "{ORDINAL}"
		pattern = pattern.replace(placeholder, str(cint(ordinal)).zfill(digits) if ordinal else "")
	return pattern


def _resolve_role_placeholders(pattern, variant):
	for row in variant.get("components") or []:
		placeholder = "{" + cstr(row.get("role")) + "}"
		if placeholder not in pattern:
			continue
		name = frappe.db.get_value(PARENT_DOCTYPE, row.get("specification"), "specification_name")
		pattern = pattern.replace(placeholder, cstr(name or row.get("specification")))
	return pattern


def make_variant_code(template_code, template_name, variant):
	if variant.specification_name and variant.specification_code:
		return

	template_doc = frappe.get_cached_doc(PARENT_DOCTYPE, template_code)
	pattern = template_doc.get("variant_name_pattern")
	pattern_result = make_code_from_pattern(pattern, variant.attributes, variant) if pattern else None

	if template_doc.get("specification_number_template"):
		from erpnext.stock.doctype.specification_number_template.specification_number_template import (
			resolve_specification_template,
		)

		variant.specification_number_template = template_doc.specification_number_template
		resolved = resolve_specification_template(variant)
		if resolved:
			variant.specification_code = resolved
			variant.specification_name = pattern_result or resolved
			return

	if pattern_result:
		variant.specification_code = pattern_result
		variant.specification_name = pattern_result
		return

	abbreviations = []
	for attr in variant.attributes:
		row = frappe.db.sql(
			f"""select a.numeric_values, v.abbr
			from `tab{ATTRIBUTE_DOCTYPE}` a left join `tab{ATTRIBUTE_VALUE_DOCTYPE}` v
				on (a.name=v.parent)
			where a.name=%(attribute)s and (v.attribute_value=%(attribute_value)s or a.numeric_values = 1)""",
			{"attribute": attr.attribute, "attribute_value": attr.attribute_value},
			as_dict=True,
		)
		if not row:
			continue
		abbreviations.append(cstr(attr.attribute_value) if row[0].numeric_values else row[0].abbr)

	if abbreviations:
		variant.specification_code = "{}-{}".format(template_code, "-".join(abbreviations))
		variant.specification_name = "{}-{}".format(template_name, "-".join(abbreviations))


@frappe.whitelist()
def create_variant_doc_for_quick_entry(template, args):
	args = json.loads(args)
	existing = get_variant(template, args)
	if existing:
		return existing
	variant = create_variant(template, args=args)
	variant.name = variant.specification_code
	validate_variant_attributes(variant, args)
	return variant.as_dict()


@frappe.whitelist()
def get_attribute_value_suggestions(parent, attribute_value):
	return frappe.get_all(
		ATTRIBUTE_VALUE_DOCTYPE,
		filters={"parent": parent, "attribute_value": ("like", f"%{attribute_value}%")},
		fields=["attribute_value"],
		limit=20,
	)


def update_variants(variants, template, publish_progress=True):
	total = len(variants)
	for count, d in enumerate(variants, start=1):
		variant = frappe.get_doc(PARENT_DOCTYPE, d)
		copy_attributes_to_variant(template, variant)
		variant.save()
		if publish_progress:
			frappe.publish_progress(count / total * 100, title=_("Updating Variants..."))
