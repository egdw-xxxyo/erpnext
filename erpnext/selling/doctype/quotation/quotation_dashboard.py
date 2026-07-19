from frappe import _


def get_data():
	return {
		"fieldname": "prevdoc_docname",
		"non_standard_fieldnames": {
			"Auto Repeat": "reference_document",
			"Quotation Version": "quotation",
		},
		"transactions": [
			{"label": _("Sales Order"), "items": ["Sales Order"]},
			{"label": _("Negotiation"), "items": ["Quotation Version"]},
			{"label": _("Subscription"), "items": ["Auto Repeat"]},
		],
	}
