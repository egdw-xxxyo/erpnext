import json
import uuid

import frappe
from frappe.model.document import Document


class DeviceScriptRun(Document):
	pass


MAX_RUNS_PER_SCRIPT = 200


def insert_run(
	script_name: str,
	timestamp,
	status: str,
	duration_ms: int,
	logs: str,
	context: dict | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str | None:
	"""Insert a Device Script Run child row directly, then prune oldest beyond MAX_RUNS_PER_SCRIPT.

	Direct SQL avoids loading the parent Device Script doc (which would race with
	concurrent script edits on busy systems).
	"""
	try:
		try:
			ctx_str = json.dumps(context or {}, ensure_ascii=False, default=str, indent=2)
		except Exception:
			ctx_str = str(context)
		row_name = uuid.uuid4().hex[:10]
		now_iso = frappe.utils.now_datetime()
		frappe.db.sql(
			"""
			INSERT INTO `tabDevice Script Run`
				(name, parent, parenttype, parentfield, idx,
				 timestamp, status, duration_ms, logs, context,
				 reference_doctype, reference_name,
				 creation, modified, owner, modified_by, docstatus)
			VALUES (%(name)s, %(parent)s, 'Device Script', 'runs', 1,
				%(timestamp)s, %(status)s, %(duration_ms)s, %(logs)s, %(context)s,
				%(ref_dt)s, %(ref_n)s,
				%(now)s, %(now)s, 'Administrator', 'Administrator', 0)
			""",
			{
				"name": row_name,
				"parent": script_name,
				"timestamp": timestamp,
				"status": status,
				"duration_ms": int(duration_ms or 0),
				"logs": logs or "",
				"context": ctx_str,
				"ref_dt": reference_doctype,
				"ref_n": reference_name,
				"now": now_iso,
			},
		)
		frappe.db.sql(
			"""
			DELETE FROM `tabDevice Script Run`
			WHERE parent = %s
			  AND name NOT IN (
			    SELECT name FROM (
			      SELECT name FROM `tabDevice Script Run`
			      WHERE parent = %s
			      ORDER BY timestamp DESC, creation DESC
			      LIMIT %s
			    ) keep_rows
			  )
			""",
			(script_name, script_name, MAX_RUNS_PER_SCRIPT),
		)
		# Re-index so newest run renders at the top of the parent grid (parent loads child rows ORDER BY idx ASC).
		frappe.db.sql("SET @rn := 0")
		frappe.db.sql(
			"""
			UPDATE `tabDevice Script Run`
			SET idx = (@rn := @rn + 1)
			WHERE parent = %s
			ORDER BY timestamp DESC, creation DESC
			""",
			(script_name,),
		)
		return row_name
	except Exception:
		frappe.log_error(title="Device Script Run insert failed")
		return None
