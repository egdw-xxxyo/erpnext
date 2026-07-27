# Backwards-compatibility shim.
#
# OTDR moved from the Manufacturing module to Devices
# (erpnext.devices.doctype.otdr.otdr_api). Deployed OTDR sync clients
# (desktop ~/git/otdr-sync, Android ~/git/otdr-sync-android) still POST to
# /api/method/erpnext.manufacturing.doctype.otdr.otdr_api.<method>, so the old
# import path keeps resolving to the same whitelisted functions.
#
# Remove once every client ships the new base path.

from erpnext.devices.doctype.otdr.otdr_api import (  # noqa: F401
	generate_connect_bundle,
	get_configuration,
	get_default_connect_url,
	parse_and_submit_measurement,
	submit_measurement,
	submit_opm_measurement,
	submit_vfl_event,
	update_status,
	who_am_i,
)
