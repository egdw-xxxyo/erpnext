"""Ідентифікаційні дані працівника: РНОКПП (ІПН).

Реєстраційний номер облікової картки платника податків — десять цифр, один на людину. Він
потрібен усюди, де зарплата виходить за межі системи (звітність, платіжки), тож перевіряємо
його одразу в картці: довжину, цифри й те, що номер ще ні за ким не записаний.

Унікальний індекс на поле не ставимо: у Frappe порожнє поле — це порожній рядок, а не NULL,
тож індекс не дав би зберегти другого працівника без номера.
"""

import frappe
from frappe import _

TAX_ID_LENGTH = 10


def validate_tax_id(doc, method=None):
	"""Employee.validate: РНОКПП має бути з десяти цифр і належати одній людині."""
	number = (doc.get("custom_tax_id") or "").strip()

	if not number:
		return

	doc.custom_tax_id = number

	if not number.isdigit() or len(number) != TAX_ID_LENGTH:
		frappe.throw(
			_("The tax number (RNOKPP) consists of {0} digits.").format(TAX_ID_LENGTH),
			title=_("Wrong Tax Number"),
		)

	twin = frappe.db.get_value(
		"Employee",
		{"custom_tax_id": number, "name": ("!=", doc.name)},
		["name", "employee_name"],
		as_dict=True,
	)

	if twin:
		frappe.throw(
			_("The tax number {0} is already recorded for {1}.").format(
				number, twin.employee_name or twin.name
			),
			title=_("The Tax Number Is Not Unique"),
		)
