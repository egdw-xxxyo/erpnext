"""Patch stock quality_inspection.py to:
1. Pull acceptance criteria from Item Specification
2. Auto-populate serial_inspections from PR bundle on insert
3. Update PR quantities on QI submit based on serial pass/fail
"""
import os
import re
import stat

QI_PY = "/home/frappe/frappe-bench/apps/erpnext/erpnext/stock/doctype/quality_inspection/quality_inspection.py"
MARKER = "_update_pr_from_serial_inspections"

# Methods to inject (replaces get_item_specification_details, adds helpers)
NEW_METHOD = '''
	@frappe.whitelist()
	def get_item_specification_details(self):
		if not self.quality_inspection_template:
			self.quality_inspection_template = frappe.db.get_value(
				"Item", self.item_code, "quality_inspection_template"
			)

		if not self.quality_inspection_template:
			return

		self.set("readings", [])
		parameters = get_template_details(self.quality_inspection_template)

		spec_values = self._resolve_spec_values()

		# When using serial inspections, readings are reference-only
		has_serial_inspections = bool(self.get("serial_inspections")) or (
			self.reference_type == "Purchase Receipt" and self.reference_name
		)

		for d in parameters:
			child = self.append("readings", {})
			child.update(d)
			child.status = "Accepted"
			if has_serial_inspections:
				child.manual_inspection = 1
			child.parameter_group = frappe.get_value(
				"Quality Inspection Parameter", d.specification, "parameter_group"
			)

			spec = spec_values.get(d.specification)
			if spec:
				if d.get("numeric") and not d.get("formula_based_criteria"):
					if not child.min_value and not child.max_value:
						child.min_value = spec.get("min_value") or 0
						child.max_value = spec.get("max_value") or 0
				elif not d.get("numeric") and not d.get("formula_based_criteria"):
					if not child.value:
						child.value = spec.get("value") or ""

		if has_serial_inspections:
			self.manual_inspection = 1

	def _resolve_spec_values(self):
		"""Load specification parameters from Item's child table."""
		if not self.item_code:
			return {}
		spec_params = frappe.get_all(
			"Item Specification Parameter",
			filters={"parent": self.item_code, "parenttype": "Item"},
			fields=["parameter", "value", "numeric", "min_value", "max_value"],
		)
		return {sp.parameter: sp for sp in spec_params}

	def before_insert(self):
		"""Prevent duplicate QI for same PR + item_code."""
		if self.reference_type != "Purchase Receipt" or not self.reference_name:
			return
		existing = frappe.db.exists("Quality Inspection", {
			"reference_type": "Purchase Receipt",
			"reference_name": self.reference_name,
			"item_code": self.item_code,
			"docstatus": ["!=", 2],
		})
		if existing:
			frappe.throw(
				f"Quality Inspection {existing} already exists for this Purchase Receipt and Item. "
				f"<a href='/app/quality-inspection/{existing}'>{existing}</a>",
				title="Duplicate Quality Inspection"
			)

	def after_insert(self):
		"""Auto-populate serial_inspections from linked PR bundle."""
		if self.reference_type != "Purchase Receipt" or not self.reference_name:
			return
		if self.get("serial_inspections"):
			return
		try:
			pr_items = frappe.get_all(
				"Purchase Receipt Item",
				filters={"parent": self.reference_name, "item_code": self.item_code},
				fields=["serial_and_batch_bundle"],
				limit=1,
			)
			if not pr_items or not pr_items[0].serial_and_batch_bundle:
				return
			entries = frappe.get_all(
				"Serial and Batch Entry",
				filters={"parent": pr_items[0].serial_and_batch_bundle},
				fields=["serial_no"],
				order_by="idx asc",
			)
			for entry in entries:
				if not entry.serial_no:
					continue
				frappe.get_doc({
					"doctype": "QI Serial Entry",
					"parent": self.name,
					"parentfield": "serial_inspections",
					"parenttype": "Quality Inspection",
					"serial_no": entry.serial_no,
					"status": "Pass",
				}).insert(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(title="QI Serial Auto-populate Error", message=str(e))

	def _update_pr_from_serial_inspections(self):
		"""Update PR item quantities based on serial pass/fail results."""
		if self.reference_type != "Purchase Receipt" or not self.reference_name:
			return
		serial_inspections = self.get("serial_inspections") or []
		if not serial_inspections:
			return
		try:
			pass_serials = [e.serial_no for e in serial_inspections if e.status == "Pass"]
			fail_serials = [e.serial_no for e in serial_inspections if e.status != "Pass"]
			pass_count = len(pass_serials)
			fail_count = len(fail_serials)
			pr_items = frappe.get_all(
				"Purchase Receipt Item",
				filters={"parent": self.reference_name, "item_code": self.item_code},
				fields=["name", "serial_and_batch_bundle", "rate", "base_rate"],
				limit=1,
			)
			if not pr_items:
				return
			pr_item = pr_items[0]
			frappe.db.set_value("Purchase Receipt Item", pr_item.name, {
				"received_qty": pass_count,
				"qty": pass_count,
				"rejected_qty": 0,
				"amount": pass_count * (pr_item.rate or 0),
				"base_amount": pass_count * (pr_item.base_rate or 0),
			})
			if fail_serials and pr_item.serial_and_batch_bundle:
				frappe.db.delete("Serial and Batch Entry", {
					"parent": pr_item.serial_and_batch_bundle,
					"serial_no": ("in", fail_serials),
				})
			frappe.db.commit()
		except Exception as e:
			frappe.log_error(title="QI Submit PR Update Error", message=str(e))
'''

# Step 1: Replace get_item_specification_details with our version + add helpers
with open(QI_PY, "r") as f:
    content = f.read()

if MARKER in content:
    print("[qi_spec_patch] Patch already applied, skipping")
else:
    # Replace get_item_specification_details
    pattern = r'(\t@frappe\.whitelist\(\)\n\tdef get_item_specification_details\(self\):.*?)(\n\t@frappe\.whitelist\(\)\n\tdef get_quality_inspection_template)'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        old_method = match.group(1)
        next_method_start = match.group(2)
        content = content.replace(old_method + next_method_start, NEW_METHOD + "\n" + next_method_start)
    else:
        simple_pattern = r'(\tdef get_item_specification_details\(self\):.*?)(\n\t(?:@frappe\.whitelist|def get_quality))'
        match2 = re.search(simple_pattern, content, re.DOTALL)
        if match2:
            old_method = match2.group(1)
            old_with_decorator = "\t@frappe.whitelist()\n" + old_method
            if old_with_decorator in content:
                old_method = old_with_decorator
            content = content.replace(old_method, NEW_METHOD.lstrip("\n"))
        else:
            print("[qi_spec_patch] ERROR: Could not find get_item_specification_details method")
            exit(1)

    # Step 2: Inject our call into the stock on_submit method
    on_submit_pattern = r'(\tdef on_submit\(self\):\n(?:\t\t.*\n)*?\t\t\tself\.update_qc_reference\(\))'
    on_submit_match = re.search(on_submit_pattern, content)
    if on_submit_match:
        old_on_submit = on_submit_match.group(1)
        new_on_submit = old_on_submit + "\n\t\tself._update_pr_from_serial_inspections()"
        content = content.replace(old_on_submit, new_on_submit)
        print("[qi_spec_patch] Injected _update_pr_from_serial_inspections into on_submit")
    else:
        fallback = re.search(r'(\tdef on_submit\(self\):.*?self\.update_qc_reference\(\))', content, re.DOTALL)
        if fallback:
            old = fallback.group(1)
            content = content.replace(old, old + "\n\t\tself._update_pr_from_serial_inspections()")
            print("[qi_spec_patch] Injected via fallback pattern")
        else:
            print("[qi_spec_patch] WARNING: No on_submit found at all")

    try:
        os.chmod(QI_PY, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH)
    except OSError:
        pass

    with open(QI_PY, "w") as f:
        f.write(content)
    print("[qi_spec_patch] Successfully patched get_item_specification_details")

print("[qi_spec_patch] Done")
