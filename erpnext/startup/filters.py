def get_filters_config():
	filters_config = {
		"fiscal year": {
			"label": "Fiscal Year",
			"get_field": "erpnext.accounts.utils.get_fiscal_year_filter_field",
			"valid_for_fieldtypes": ["Date", "Datetime", "DateRange"],
			"depends_on": "company",
		},
		"last three days": {
			"label": "Last Three Days",
			"get_field": "erpnext.utilities.todo.get_recent_assignment_filter",
			"valid_for_fieldtypes": ["Date"],
			"data": {"fieldtype": "Select", "options": ["Last Three Days"]},
		},
		"before now": {
			"label": "Before Now",
			"get_field": "erpnext.utilities.todo.get_before_now_filter",
			"valid_for_fieldtypes": ["Datetime"],
			"data": {"fieldtype": "Select", "options": ["Now"]},
		},
		"next 24 hours": {
			"label": "Next 24 Hours",
			"get_field": "erpnext.utilities.todo.get_next_24_hours_filter",
			"valid_for_fieldtypes": ["Datetime"],
			"data": {"fieldtype": "Select", "options": ["Next 24 Hours"]},
		},
	}

	return filters_config
