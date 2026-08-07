import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TEMPLATE = "BPLA-UKR-FO"
SPEC_TEMPLATE_NAME = "FPV Drone Spec"
ATTR_NAME = "Шифр FPV код"

CAM_QQ = {
	"Денна аналогова": "01",
	"Термальна аналогова": "02",
	"Комбіновані Денна та Термальна аналогові": "03",
	"Денна цифрова": "04",
	"Термальна цифрова": "05",
	"Комбіновані Денна та Термальна цифрові": "06",
}

# Size 10: ww depends on length; ee per length.
S10 = {
	5: ("12", "11"),
	10: ("13", "12"),
	15: ("13", "13"),
	20: ("13", "21"),
	25: ("13", "22"),
}

# Size 15: (length, spool) → (ww, ee)
S15 = {
	(15, "125мм 0.25"): ("21", "13"),
	(20, "125мм 0.2"): ("22", "21"),
	(25, "125мм 0.2"): ("22", "22"),
	(15, "150мм 0.25"): ("22", "31"),
	(20, "150мм 0.25"): ("22", "32"),
	(25, "150мм 0.25"): ("22", "33"),
	(30, "150мм 0.2"): ("23", "41"),
	(40, "150мм 0.2"): ("24", "42"),
}


def execute():
	_ensure_ported_fields()
	_ensure_custom_field()
	if not frappe.db.exists("Item", TEMPLATE):
		return

	_ensure_short_names_on_cameras()
	_ensure_size_short_names()
	_ensure_shifr_attr_values()
	_ensure_attr_on_template()
	_set_shifr_code_per_variant()
	_ensure_spec_template_doc()
	_link_template_on_bpla()
	_resave_variants()
	frappe.db.commit()


def _ensure_ported_fields():
	"""`Item Attribute Value.short_name` is a Custom Field on version-16.

	Patches run before ./deploy calls setup_custom_fields, so create it here first —
	otherwise the set_value calls below hit an unknown column. Idempotent."""
	from erpnext.patches.setup_custom_fields import create_v16_ported_fields

	create_v16_ported_fields()
	frappe.reload_doctype("Item Attribute Value")


def _ensure_custom_field():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "specification_number_template",
					"fieldtype": "Link",
					"label": "Specification Number Template",
					"options": "Specification Number Template",
					"insert_after": "serial_number_template",
				},
			]
		}
	)


def _ensure_short_names_on_cameras():
	if not frappe.db.has_column("Item Attribute Value", "short_name"):
		return

	for full, qq in CAM_QQ.items():
		exists = frappe.db.exists(
			"Item Attribute Value",
			{"parent": "Тип камери", "attribute_value": full},
		)
		if exists:
			frappe.db.set_value("Item Attribute Value", exists, "short_name", qq, update_modified=False)


def _ensure_size_short_names():
	if not frappe.db.has_column("Item Attribute Value", "short_name"):
		return

	for full, sn in (('10"', "10"), ('15"', "15")):
		exists = frappe.db.exists(
			"Item Attribute Value",
			{"parent": "Розмір рами", "attribute_value": full},
		)
		if exists:
			frappe.db.set_value("Item Attribute Value", exists, "short_name", sn, update_modified=False)


def _build_shifr_codes():
	"""Build deterministic 4-digit code (WW+EE) for each variant of BPLA-UKR-FO."""
	rows = frappe.db.sql(
		"""SELECT iv.name, iva_size.attribute_value AS size, iva_cam.attribute_value AS cam,
				iva_len.attribute_value AS length, iva_sp.attribute_value AS spool
		FROM `tabItem` iv
		LEFT JOIN `tabItem Variant Attribute` iva_size
			ON iva_size.parent=iv.name AND iva_size.attribute='Розмір рами'
		LEFT JOIN `tabItem Variant Attribute` iva_cam
			ON iva_cam.parent=iv.name AND iva_cam.attribute='Тип камери'
		LEFT JOIN `tabItem Variant Attribute` iva_len
			ON iva_len.parent=iv.name AND iva_len.attribute='Довжина намотки'
		LEFT JOIN `tabItem Variant Attribute` iva_sp
			ON iva_sp.parent=iv.name AND iva_sp.attribute='Тип котушки FO'
		WHERE iv.variant_of=%s""",
		(TEMPLATE,),
		as_dict=True,
	)
	out = {}
	for r in rows:
		size_raw = (r.size or "").replace('"', "")
		length_int = int((r.length or "0").split()[0])
		if size_raw == "10":
			ww, ee = S10.get(length_int, ("", ""))
		elif size_raw == "15":
			ww, ee = S15.get((length_int, r.spool), ("", ""))
		else:
			continue
		if ww and ee:
			out[r.name] = ww + "00" + ee
	return out


def _ensure_shifr_attr_values():
	codes = sorted({c for c in _build_shifr_codes().values()})
	if not codes:
		return
	if not frappe.db.exists("Item Attribute", ATTR_NAME):
		doc = frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": ATTR_NAME,
				"item_attribute_values": [{"attribute_value": c, "abbr": c} for c in codes],
			}
		)
		doc.insert(ignore_permissions=True)
		return
	doc = frappe.get_doc("Item Attribute", ATTR_NAME)
	existing = {r.attribute_value for r in doc.item_attribute_values}
	for c in codes:
		if c not in existing:
			doc.append("item_attribute_values", {"attribute_value": c, "abbr": c})
	doc.save(ignore_permissions=True)


def _ensure_attr_on_template():
	tmpl = frappe.get_doc("Item", TEMPLATE)
	if any(a.attribute == ATTR_NAME for a in tmpl.attributes):
		return
	tmpl.append("attributes", {"attribute": ATTR_NAME})
	tmpl.flags.ignore_validate = True
	tmpl.flags.ignore_mandatory = True
	tmpl.save(ignore_permissions=True)


def _set_shifr_code_per_variant():
	codes = _build_shifr_codes()
	for variant, code in codes.items():
		# Insert or update Item Variant Attribute row
		existing = frappe.db.exists(
			"Item Variant Attribute",
			{"parent": variant, "attribute": ATTR_NAME},
		)
		if existing:
			frappe.db.set_value(
				"Item Variant Attribute", existing, "attribute_value", code, update_modified=False
			)
		else:
			row_name = frappe.generate_hash(length=10)
			frappe.db.sql(
				"""INSERT INTO `tabItem Variant Attribute`
				(name, creation, modified, owner, modified_by, parent, parenttype, parentfield, idx, attribute, attribute_value)
				VALUES (%s, NOW(), NOW(), 'Administrator', 'Administrator', %s, 'Item', 'attributes',
				(SELECT COALESCE(MAX(idx),0)+1 FROM `tabItem Variant Attribute` t WHERE t.parent=%s), %s, %s)""",
				(row_name, variant, variant, ATTR_NAME, code),
			)


def _ensure_spec_template_doc():
	if frappe.db.exists("Specification Number Template", SPEC_TEMPLATE_NAME):
		return
	doc = frappe.get_doc(
		{
			"doctype": "Specification Number Template",
			"template_name": SPEC_TEMPLATE_NAME,
			"description": "FPV drone specification: УКРП.200121.{size}{cam}{ww}00{ee}С",
			"components": [
				{"component_type": "Literal", "value": "УКРП.200121."},
				{"component_type": "Item Attribute Short Name", "attribute_link": "Розмір рами"},
				{"component_type": "Item Attribute Short Name", "attribute_link": "Тип камери"},
				{"component_type": "Item Attribute Abbr", "attribute_link": ATTR_NAME},
				{"component_type": "Literal", "value": "С"},
			],
		}
	)
	doc.insert(ignore_permissions=True)


def _link_template_on_bpla():
	frappe.db.set_value(
		"Item", TEMPLATE, "specification_number_template", SPEC_TEMPLATE_NAME, update_modified=False
	)


def _resave_variants():
	"""Resave each variant so the validate hook recomputes custom_шифр from template."""
	for variant in frappe.get_all("Item", filters={"variant_of": TEMPLATE}, pluck="name"):
		try:
			doc = frappe.get_doc("Item", variant)
			doc.flags.ignore_validate = False
			doc.save(ignore_permissions=True)
		except Exception as e:
			print(f"  WARN failed to resave {variant}: {e}")
