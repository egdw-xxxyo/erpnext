# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""A step on a quantity that is measured rather than chosen.

The range fields of `Product Attribute` are modelled on `Item Attribute`, where the step
generates the values a variant may take. Here nothing is generated — a person types the
value — so the step is only a refusal, and on «Маса, кг» it refused the truth: a
modification that weighs 7.3 kg could not say so, because the attribute was given a step
of 0.5 along with the fields it was copied from. A step is right for a quantity that comes
in fixed sizes, like a fibre length in whole kilometres; it is wrong for one that comes off
a scale.

The range stays as it is: 0 to 50 kg still rejects a decimal point in the wrong place. Only
the step goes, and only on the attributes named here, because which quantities are measured
is not something the schema knows.
"""

import frappe

from erpnext.technical_documentation.constants import ATTRIBUTE_DOCTYPE

MEASURED_ATTRIBUTES = ("Маса, кг",)


def execute():
	for attribute in MEASURED_ATTRIBUTES:
		if frappe.db.get_value(ATTRIBUTE_DOCTYPE, attribute, "increment"):
			frappe.db.set_value(ATTRIBUTE_DOCTYPE, attribute, "increment", 0, update_modified=False)
