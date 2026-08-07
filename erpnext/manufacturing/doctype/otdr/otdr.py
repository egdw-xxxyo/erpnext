# Backwards-compatibility shim — see otdr_api.py in this folder.
# Real implementation: erpnext.devices.doctype.otdr.otdr

from erpnext.devices.doctype.otdr.otdr import (
	OTDR,
	get_status,
	set_sync_listening,
)
