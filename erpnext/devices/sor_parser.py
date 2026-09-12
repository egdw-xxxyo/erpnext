"""Parse a Bellcore/Telcordia `.sor` trace into a plain dict.

Moved verbatim out of `otdr_api._parse_sor_file` so the parser outlives the OTDR doctype.
Pure `path -> dict` with no frappe import: the only dependency is the `otdrs` Rust wheel.

This is the single source of truth for SOR parsing. Clients upload raw bytes and never
parse on-device — see the server-side-parsing invariant in CLAUDE.md; silent client-side
parse failures have burned real debugging time before.
"""


def parse_sor_file(path: str) -> dict:
	"""Parse SOR file via otdrs Rust wheel. Mirrors desktop read_sor_info."""
	from datetime import datetime, timezone

	import otdrs

	def g(o, k, d=None):
		try:
			v = getattr(o, k, d)
		except Exception:
			return d
		return v if v is not None else d

	def first(seq, d=0):
		try:
			return seq[0] if seq else d
		except Exception:
			return d

	def evt_str(t):
		if t is None:
			return ""
		try:
			b = bytes(t) if not isinstance(t, bytes | bytearray | str) else t
			if isinstance(b, bytes | bytearray):
				return b.decode("ascii", errors="replace").strip()
			return str(b).strip()
		except Exception:
			return str(t)

	sor = otdrs.parse_file(path)
	gp, fp, sp, ke = sor.general_parameters, sor.fixed_parameters, sor.supplier_parameters, sor.key_events

	ts = g(fp, "date_time_stamp", 0)
	try:
		dt_iso = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts else ""
	except Exception:
		dt_iso = str(ts)

	events = []
	for i, e in enumerate(g(ke, "key_events", []) or []):
		prop = g(e, "event_propogation_time", 0) or 0
		events.append(
			{
				"index": g(e, "event_number", i + 1),
				"distance_km": round(prop / 10000.0, 4),
				"event_code": evt_str(g(e, "event_code", "")),
				"slope_db_per_km": round((g(e, "attenuation_coefficient_lead_in_fiber", 0) or 0) / 1000.0, 4),
				"splice_loss_db": round((g(e, "event_loss", 0) or 0) / 1000.0, 4),
				"reflectance_db": round((g(e, "event_reflectance", 0) or 0) / 1000.0, 4),
				"loss_measurement_technique": g(e, "loss_measurement_technique", ""),
				"comment": g(e, "comment", ""),
			}
		)

	last = g(ke, "last_key_event", None)
	end_to_end_db = round((g(last, "end_to_end_loss", 0) or 0) / 1000.0, 4) if last else None
	orl_db = round((g(last, "optical_return_loss", 0) or 0) / 1000.0, 4) if last else None
	last_prop = (g(last, "event_propogation_time", 0) or 0) if last else 0
	fiber_length_km = round(last_prop / 10000.0, 4) if last else None

	if last:
		events.append(
			{
				"index": g(last, "event_number", len(events) + 1),
				"distance_km": round(last_prop / 10000.0, 4),
				"event_code": evt_str(g(last, "event_code", "")),
				"slope_db_per_km": round(
					(g(last, "attenuation_coefficient_lead_in_fiber", 0) or 0) / 1000.0, 4
				),
				"splice_loss_db": round((g(last, "event_loss", 0) or 0) / 1000.0, 4),
				"reflectance_db": round((g(last, "event_reflectance", 0) or 0) / 1000.0, 4),
				"loss_measurement_technique": g(last, "loss_measurement_technique", ""),
				"comment": g(last, "comment", ""),
				"is_end_of_fiber": True,
			}
		)

	return {
		"Acquisition": {
			"wavelength_nm": round((g(fp, "actual_wavelength", 0) or 0) / 10.0, 1),
			"pulse_width_ns": first(g(fp, "pulse_widths_used", []) or [], 0),
			"range_km": round((g(fp, "acquisition_range", 0) or 0) / 1000.0, 4),
			"averages": g(fp, "number_of_averages", 0),
			"averaging_time_s": g(fp, "averaging_time", 0),
			"date_time_utc": dt_iso,
			"units": g(fp, "units_of_distance", ""),
			"trace_type": g(fp, "trace_type", ""),
		},
		"Fiber": {
			"group_index": round((g(fp, "group_index", 0) or 0) / 100000.0, 5),
			"backscatter_db": -round((g(fp, "backscatter_coefficient", 0) or 0) / 10.0, 1),
			"loss_threshold_db": round((g(fp, "loss_threshold", 0) or 0) / 1000.0, 3),
			"reflectance_threshold_db": -round((g(fp, "reflectance_threshold", 0) or 0) / 1000.0, 3),
			"end_of_fibre_threshold_db": round((g(fp, "end_of_fibre_threshold", 0) or 0) / 1000.0, 3),
		},
		"General": {
			"fiber_id": g(gp, "fiber_id", ""),
			"cable_id": g(gp, "cable_id", ""),
			"operator": g(gp, "operator", ""),
			"comment": g(gp, "comment", ""),
			"originating_location": g(gp, "originating_location", ""),
			"terminating_location": g(gp, "terminating_location", ""),
			"nominal_wavelength_nm": g(gp, "nominal_wavelength", 0),
			"fiber_type": g(gp, "fiber_type", 0),
		},
		"Supplier": {
			"supplier_name": g(sp, "supplier_name", ""),
			"mainframe_id": g(sp, "otdr_mainframe_id", ""),
			"mainframe_sn": g(sp, "otdr_mainframe_sn", ""),
			"module_id": g(sp, "optical_module_id", ""),
			"module_sn": g(sp, "optical_module_sn", ""),
			"software_revision": g(sp, "software_revision", ""),
		},
		"Events": events,
		"Summary": {
			"n_events": g(ke, "number_of_key_events", len(events)),
			"fiber_length_km": fiber_length_km,
			"end_to_end_loss_db": end_to_end_db,
			"optical_return_loss_db": orl_db,
		},
	}


def flatten_measurement(sor_info: dict) -> dict:
	"""The convenience keys scripts read off the top level of a measurement payload.

	Mirrors what `parse_and_submit_measurement` built inline, kept next to the parser so the
	payload shape has one owner.
	"""
	out: dict = {}
	if not sor_info:
		return out

	summary = sor_info.get("Summary") or {}
	acq = sor_info.get("Acquisition") or {}
	if "end_to_end_loss_db" in summary:
		out["loss_db"] = summary["end_to_end_loss_db"]
	if "fiber_length_km" in summary:
		out["distance_km"] = summary["fiber_length_km"]
	if "optical_return_loss_db" in summary:
		out["orl_db"] = summary["optical_return_loss_db"]
	if "wavelength_nm" in acq:
		out["wavelength_nm"] = acq["wavelength_nm"]
	return out
