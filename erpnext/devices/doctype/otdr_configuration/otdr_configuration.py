from frappe.model.document import Document


class OTDRConfiguration(Document):
	"""Sync and BLE settings for the phone measuring at a workplace.

	These settings outlived the `OTDR` doctype they used to hang off: they describe the
	reflectometer and the sync loop, which did not change when device identity was replaced
	by workplace identity. `Workplace.otdr_configuration` points here now, and the phone
	fetches them through `otdr_measurement_api.get_configuration`.

	`on_update` used to push the new config to the device over realtime, addressed to the
	OTDR record's `last_used_by`. There is no device record to address any more, and the app
	re-reads the configuration when the operator picks a workplace, so the push is gone
	rather than reimplemented.
	"""

	pass
