import frappe

# DocTypes relocated from Manufacturing/Stock into the new "Devices" module.
# Permissions live in each DocType's JSON `permissions` block (synced on migrate);
# this patch only guarantees the Module Def, the new Roles, the module reassignment
# on existing records, and a one-time backfill so current users keep access.
MOVED_DOCTYPES = [
	"Scanner",
	"Scanner Configuration",
	"Scanner Scan Log",
	"Scanner Scan Log Entry",
	"Scanner Setup",
	"Scan Test Case",
	"Device Script",
	"Device Script Run",
	"Device Script Version",
	"Label Template",
	"Label Template Example",
	"Label Printer",
	"Label Size",
	"Print Job",
	"Scanner Command",
	"Item Label Template",
]

NEW_ROLES = ["Device Manager", "Device Operator"]

# Existing users holding the old role get the matching new role (one-time backfill).
ROLE_BACKFILL = [
	("Manufacturing Manager", "Device Manager"),
	("Manufacturing User", "Device Operator"),
]


def execute():
	# 1. Module Def (modules.txt sync also creates it; be explicit for safety).
	if not frappe.db.exists("Module Def", "Devices"):
		frappe.get_doc({
			"doctype": "Module Def",
			"module_name": "Devices",
			"app_name": "erpnext",
		}).insert(ignore_permissions=True)

	# 2. Reassign module on existing DocType records (JSON sync also does this).
	for dt in MOVED_DOCTYPES:
		if frappe.db.exists("DocType", dt):
			frappe.db.set_value("DocType", dt, "module", "Devices", update_modified=False)

	# 3. Create the new roles idempotently (perms come from JSON permissions blocks).
	for role in NEW_ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({
				"doctype": "Role",
				"role_name": role,
				"desk_access": 1,
			}).insert(ignore_permissions=True)

	# 4. Backfill: give current holders of the Manufacturing roles the matching
	#    Device role so scanner/label access is not lost by the module move.
	for src, dst in ROLE_BACKFILL:
		users = frappe.get_all("Has Role", filters={"role": src, "parenttype": "User"}, pluck="parent")
		for user in set(users):
			if not user or user in ("Administrator", "Guest"):
				continue
			if frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": dst}):
				continue
			doc = frappe.get_doc("User", user)
			doc.append("roles", {"role": dst})
			doc.save(ignore_permissions=True)

	frappe.clear_cache()
