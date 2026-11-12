frappe.provide("erpnext.sensitive_log");

erpnext.sensitive_log = (() => {
	const SHORT_PARTS = 2;
	const COLORS = {
		Unlocked: "green",
		"Wrong PIN": "orange",
		"PIN Blocked": "red",
		"PIN Set": "blue",
		"PIN Changed": "blue",
		"PIN Reset": "blue",
		"Reset Requested": "blue",
		Locked: "gray",
		Expired: "gray",
		"Settings Changed": "purple",
	};
	const LABELS = { Expired: __("Closed"), "Settings Changed": __("Settings") };
	const BROWSERS = [
		[/Edg\//, "Edge"],
		[/OPR\//, "Opera"],
		[/Firefox\//, "Firefox"],
		[/Chrome\//, "Chrome"],
		[/Version\/.*Safari\//, "Safari"],
		[/python-requests|curl\/|okhttp/i, __("API client")],
	];
	const SYSTEMS = [
		[/Windows/, "Windows"],
		[/Android/, "Android"],
		[/iPhone|iPad/, "iOS"],
		[/Mac OS X/, "macOS"],
		[/Linux/, "Linux"],
	];

	const time_of = (value, since) => {
		if (!value) return "";
		const local = (datetime) => moment(frappe.datetime.convert_to_user_tz(datetime));
		const moment_value = local(value);
		return moment_value.isSame(local(since), "day")
			? moment_value.format("HH:mm")
			: moment_value.format("DD.MM HH:mm");
	};

	const parse_details = (doc) => {
		try {
			return JSON.parse(doc.details || "{}") || {};
		} catch (e) {
			return {};
		}
	};

	const object_label = (row) => __(row.label || row.object_name);
	const field_label = (row) => `${__(row.label || row.fieldname)} (${__(row.document_type)})`;
	const names = (rows, label) => (rows || []).map(label).join(", ");

	const settings_parts = (delta) =>
		[
			delta.enabled && (delta.enabled[1] ? __("protection turned on") : __("protection turned off")),
			delta.unlock_minutes &&
				__("unlock duration {0} → {1} min", [
					delta.unlock_minutes[0] || 0,
					delta.unlock_minutes[1] || 0,
				]),
			delta.idle_minutes &&
				__("idle limit {0} → {1} min", [delta.idle_minutes[0] || 0, delta.idle_minutes[1] || 0]),
			delta.max_attempts &&
				__("attempts {0} → {1}", [delta.max_attempts[0] || 0, delta.max_attempts[1] || 0]),
			delta.objects_added && __("protected: {0}", [names(delta.objects_added, object_label)]),
			delta.objects_removed && __("unprotected: {0}", [names(delta.objects_removed, object_label)]),
			delta.fields_added && __("hidden fields: {0}", [names(delta.fields_added, field_label)]),
			delta.fields_removed && __("shown fields: {0}", [names(delta.fields_removed, field_label)]),
			...(delta.objects_minutes || []).map((row) =>
				__("{0}: {1} → {2} min", [object_label(row), row.was || 0, row.now || 0])
			),
			delta.api_users_added &&
				__("API access granted: {0}", [names(delta.api_users_added, (row) => row.user)]),
			delta.api_users_removed &&
				__("API access removed: {0}", [names(delta.api_users_removed, (row) => row.user)]),
		].filter(Boolean);

	const settings_text = (doc) => {
		const parts = settings_parts(parse_details(doc));
		if (!parts.length) return { short: __("Settings Changed"), full: __("Settings Changed") };
		const shown = parts.slice(0, SHORT_PARTS).join("; ");
		const rest = parts.length - SHORT_PARTS;
		return {
			short: `${__("Settings Changed")}: ${shown}${rest > 0 ? ` ${__("and {0} more", [rest])}` : ""}`,
			full: `${__("Settings Changed")}:\n${parts.join("\n")}`,
		};
	};

	const event_text = (doc) => {
		const at = time_of(doc.expires_on, doc.creation);
		const by_manager = Boolean(doc.actor);
		const texts = {
			Unlocked: () => (at ? __("Unlocked until {0}", [at]) : __("Unlocked")),
			"Wrong PIN": () => (doc.details ? __("Wrong PIN · attempt {0}", [doc.details]) : __("Wrong PIN")),
			"PIN Blocked": () => __("PIN blocked after too many attempts"),
			"PIN Set": () => __("PIN created"),
			"PIN Changed": () => __("PIN changed"),
			"PIN Reset": () =>
				by_manager ? __("PIN reset by a manager") : __("PIN replaced with the login password"),
			"Reset Requested": () => __("PIN reset requested by email"),
			Locked: () => (by_manager ? __("Locked by a manager") : __("Locked manually")),
			Expired: () =>
				doc.details === "idle"
					? __("Closed for inactivity at {0}", [at])
					: __("Closed, the unlock time ran out at {0}", [at]),
		};
		return texts[doc.event]?.() ?? __(doc.event);
	};

	const describe = (doc) =>
		doc.event === "Settings Changed"
			? settings_text(doc)
			: { short: event_text(doc), full: event_text(doc) };

	const client_text = (agent) => {
		if (!agent) return "";
		const browser = BROWSERS.find(([pattern]) => pattern.test(agent))?.[1];
		const system = SYSTEMS.find(([pattern]) => pattern.test(agent))?.[1];
		return [browser, system].filter(Boolean).join(" · ") || agent.slice(0, 60);
	};

	const tooltip = (doc) =>
		[describe(doc).full, [doc.ip_address, client_text(doc.user_agent)].filter(Boolean).join(" · ")]
			.filter(Boolean)
			.join("\n");

	const color = (event) => COLORS[event] || "gray";
	const label = (event) => LABELS[event] || __(event);

	return { EVENTS: Object.keys(COLORS), describe, client_text, tooltip, color, label };
})();
