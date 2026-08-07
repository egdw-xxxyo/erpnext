import frappe

BPAK_SPECS = [
	("BPAK-TMPL-U07", "BpAK U07 Spec", "УКРП.463145.005С"),
	("BPAK-TMPL-U08", "BpAK U08 Spec", "УКРП.463145.002"),
	("BPAK-TMPL-U10", "BpAK U10 Spec", "УКРП.463145.001"),
	("BPAK-TMPL-U10-FO", "BpAK U10-FO Spec", "УКРП.200121.101"),
	("BPAK-TMPL-U13", "BpAK U13 Spec", "УКРП.463145.003С"),
	("BPAK-TMPL-U15", "BpAK U15 Spec", "УКРП.463145.004С"),
	("BPAK-TMPL-U15-FO", "BpAK U15-FO Spec", "УКРП.463145.006С"),
]


def execute():
	for bpak_name, spec_name, literal in BPAK_SPECS:
		if not frappe.db.exists("BpAK Template", bpak_name):
			continue
		_ensure_spec_template(spec_name, literal)
		frappe.db.set_value(
			"BpAK Template",
			bpak_name,
			"specification_number_template",
			spec_name,
			update_modified=False,
		)
		try:
			doc = frappe.get_doc("BpAK Template", bpak_name)
			doc.save(ignore_permissions=True)
		except Exception as e:
			print(f"  WARN failed to resave {bpak_name}: {e}")
	frappe.db.commit()


def _ensure_spec_template(spec_name, literal):
	if frappe.db.exists("Specification Number Template", spec_name):
		frappe.db.set_value(
			"Specification Number Template",
			spec_name,
			"description",
			f"BpAK: {literal}",
			update_modified=False,
		)
		existing = frappe.get_doc("Specification Number Template", spec_name)
		existing.set("components", [])
		existing.append("components", {"component_type": "Literal", "value": literal})
		existing.save(ignore_permissions=True)
		return
	doc = frappe.get_doc(
		{
			"doctype": "Specification Number Template",
			"template_name": spec_name,
			"description": f"BpAK: {literal}",
			"components": [
				{"component_type": "Literal", "value": literal},
			],
		}
	)
	doc.insert(ignore_permissions=True)
