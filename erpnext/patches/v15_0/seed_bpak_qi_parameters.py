import frappe

PARAMETERS = [
	"Шифр",
	"Паспорт",
	"Найменування",
	"Код виробу",
	"Розмір",
	"Камера",
	"Батарея",
	"Котушка",
	"Максимальна дальність",
	"Максимальна тривалість",
	"Довжина намотки",
]


def execute():
	for name in PARAMETERS:
		if frappe.db.exists("Quality Inspection Parameter", {"parameter": name}):
			continue
		doc = frappe.get_doc({
			"doctype": "Quality Inspection Parameter",
			"parameter": name,
		})
		doc.insert(ignore_permissions=True)
		print(f"  Created Quality Inspection Parameter: {name}")
	frappe.db.commit()
