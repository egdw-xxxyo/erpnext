# Device Script "Spool QC v1"
#   script_type   = Reflectometer
#   trigger_event = SOR Uploaded
#
# Versioned source of truth for the body stored in the Device Script DocType. Keep the two
# in sync: the DB copy is what actually runs (see `run_scripts_for_event` in
# erpnext/devices/doctype/device_script/device_script.py), this file is what gets reviewed.
#
# The script stays this thin on purpose — all logic lives in the repo module so it is
# linted, versioned and identical across sites.

from erpnext.devices.spool_qc import handle_sor_uploaded


def on_event(ctx):
	handle_sor_uploaded(ctx.otdr, ctx.payload, log=ctx.log)
