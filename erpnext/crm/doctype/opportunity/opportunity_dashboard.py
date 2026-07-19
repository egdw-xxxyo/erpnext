from frappe import _


def get_data():
	return {
		"fieldname": "opportunity",
		"transactions": [
			{"items": ["Quotation", "Request for Quotation", "Supplier Quotation"]},
			{"label": _("Negotiation"), "items": ["Quotation Version"]},
		],
	}
