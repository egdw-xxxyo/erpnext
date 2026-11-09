frappe.provide("erpnext.permission_log");

erpnext.permission_log = (() => {
	const RIGHTS = [
		"read",
		"write",
		"create",
		"delete",
		"submit",
		"cancel",
		"amend",
		"report",
		"export",
		"import",
		"print",
		"email",
		"share",
		"select",
		"mask",
		"impersonate",
		"if_owner",
	];
	const docperm_roles = {};
	const parsed = new WeakMap();

	const parse = (doc) => {
		if (!parsed.has(doc)) {
			let changes = {};
			try {
				changes = JSON.parse(doc.changes || "{}");
			} catch (e) {
				changes = {};
			}
			parsed.set(doc, { from: changes.from || {}, to: changes.to || {} });
		}
		return parsed.get(doc);
	};

	const current = (doc) => (doc.status === "Removed" ? parse(doc).from : parse(doc).to);
	const label = (key) => __(frappe.model.unscrub(key));
	const is_empty = (value) => value === "" || value === null || value === undefined;
	const join = (list) => list.join(", ");
	const items = (value) =>
		(Array.isArray(value) ? value : []).map((row) => __(row.role || row.module || Object.values(row)[0]));
	const user_name = (user) => frappe.user_info(user)?.fullname || user;
	const change = (short, lines) => ({ short, full: lines.filter(Boolean).join("\n") });

	const list_change = (key, from, to) => {
		const added = items(to);
		const removed = items(from);
		if (!added.length && !removed.length) return null;
		const detailed = [...added.map((item) => `+${item}`), ...removed.map((item) => `−${item}`)];
		const counted = [added.length && `+${added.length}`, removed.length && `−${removed.length}`];
		const short = `${label(key)}: ${
			detailed.length <= 2 ? join(detailed) : counted.filter(Boolean).join(" ")
		}`;
		return change(short, [
			`${label(key)}:`,
			added.length && `+ ${join(added)}`,
			removed.length && `− ${join(removed)}`,
		]);
	};

	const docperm_change = (doc) => {
		const { from, to } = parse(doc);
		const role = to.role || from.role || docperm_roles[doc.reference];
		const level = Number(to.permlevel || from.permlevel || 0);
		const head = [role && `${__("Role")}: ${__(role)}`, level && `${label("permlevel")}: ${level}`];
		const name = role ? __(role) : __("Permissions");
		const who = level ? `${name} (${__("Level {0}", [level])})` : name;
		if (doc.status === "Updated") {
			const granted = RIGHTS.filter((right) => right in to && Number(to[right])).map(label);
			const revoked = RIGHTS.filter((right) => right in to && !Number(to[right])).map(label);
			const changes = [...granted.map((right) => `+${right}`), ...revoked.map((right) => `−${right}`)];
			const short = changes.length <= 2 ? join(changes) : __("{0} rights changed", [changes.length]);
			return change(`${who}: ${short}`, [
				...head,
				granted.length && __("Granted: {0}", [join(granted)]),
				revoked.length && __("Revoked: {0}", [join(revoked)]),
			]);
		}
		const value = current(doc);
		const rights = RIGHTS.filter((right) => right !== "if_owner" && Number(value[right])).map(label);
		return change(`${who}: ${doc.status === "Added" ? __("access granted") : __("access removed")}`, [
			...head,
			__("Rights: {0}", [join(rights) || "—"]),
			Number(value.if_owner) && __("Own documents only"),
		]);
	};

	const user_permission_change = (doc) => {
		const value = current(doc);
		return change(`${__(value.allow || "")} = ${value.for_value || ""}`, [
			`${__("User")}: ${user_name(value.user)}`,
			`${__(value.allow || "")}: ${value.for_value || ""}`,
			`${__("Applies to")}: ${
				value.applicable_for ? __(value.applicable_for) : __("All document types")
			}`,
			Number(value.is_default) && label("is_default"),
			Number(value.hide_descendants) && label("hide_descendants"),
		]);
	};

	const property_setter_change = (doc) => {
		const { from, to } = parse(doc);
		const value = current(doc);
		const field = value.field_name || __("DocType");
		const updated = doc.status === "Updated";
		const shown = updated ? `${from.value ?? ""} → ${to.value ?? ""}` : value.value ?? "";
		return change(`${field}: ${value.property} ${shown}`, [
			`${__("Field")}: ${field}`,
			`${__("Property")}: ${value.property}`,
			updated ? __("Was: {0}", [from.value ?? ""]) : `${__("Value")}: ${value.value ?? ""}`,
			updated && __("Now: {0}", [to.value ?? ""]),
		]);
	};

	const generic_change = (doc) => {
		const { from, to } = parse(doc);
		const field =
			doc.reference_type === "Custom Field" && doc.reference
				? doc.reference.replace(`${doc.for_document}-`, "")
				: "";
		const parts = [...new Set([...Object.keys(from), ...Object.keys(to)])]
			.map((key) => {
				if (Array.isArray(from[key]) || Array.isArray(to[key]))
					return list_change(key, from[key], to[key]);
				const text =
					doc.status === "Updated"
						? `${label(key)}: ${from[key] ?? ""} → ${to[key] ?? ""}`
						: !is_empty(current(doc)[key]) && `${label(key)} = ${current(doc)[key]}`;
				return text && change(text, [text]);
			})
			.filter(Boolean);
		if (!parts.length) return change(field || "—", [field]);
		const more = parts.length > 1 ? ` (+${parts.length - 1})` : "";
		return change(`${field ? `${field}: ` : ""}${parts[0].short}${more}`, [
			field && `${__("Field")}: ${field}`,
			...parts.map((part) => part.full),
		]);
	};

	const describe = (doc) => {
		if (doc.reference_type === "Custom DocPerm") return docperm_change(doc);
		if (doc.reference_type === "Property Setter") return property_setter_change(doc);
		if (doc.for_doctype === "User Permission") return user_permission_change(doc);
		return generic_change(doc);
	};

	const object_link = (doc) => {
		if (doc.for_doctype === "DocType")
			return `/desk/permission-manager/${encodeURIComponent(doc.for_document)}`;
		return frappe.utils.get_form_link(doc.for_doctype, doc.for_document);
	};

	const object_html = (doc) => {
		if (doc.for_doctype === "User") return erpnext.entity.user(doc.for_document, { size: 20 });
		if (doc.for_doctype === "User Permission" && current(doc).user)
			return erpnext.entity.user(current(doc).user, { size: 20 });
		return erpnext.entity.html(
			{
				name: __(doc.for_document),
				sub: __(doc.for_doctype),
				key: doc.for_doctype,
				icon: doc.for_doctype === "DocType" ? "fa fa-shield" : "fa fa-file-text-o",
				href: object_link(doc),
			},
			{ size: 20 }
		);
	};

	const load_roles = (docs) => {
		const names = [
			...new Set(
				docs
					.filter((doc) => doc.reference_type === "Custom DocPerm" && doc.reference)
					.filter((doc) => !parse(doc).to.role && !parse(doc).from.role)
					.map((doc) => doc.reference)
					.filter((name) => !(name in docperm_roles))
			),
		];
		if (!names.length) return Promise.resolve(false);
		names.forEach((name) => (docperm_roles[name] = null));
		return frappe.db
			.get_list("Custom DocPerm", {
				filters: { name: ["in", names] },
				fields: ["name", "role"],
				limit: names.length,
			})
			.then((rows) => {
				rows.forEach((row) => (docperm_roles[row.name] = row.role));
				return rows.length > 0;
			});
	};

	const users_of = (doc) => [
		doc.changed_by,
		doc.for_doctype === "User" ? doc.for_document : current(doc).user,
	];

	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const is_flag = (key) => RIGHTS.includes(key) || /^(is_|hide_|apply_|ignore_)/.test(key);
	const KEY_ORDER = ["role", "permlevel", ...RIGHTS];

	const value_html = (key, value) => {
		if (is_empty(value)) return `<span class="text-muted">—</span>`;
		if (is_flag(key)) return Number(value) ? __("Yes") : __("No");
		if (key === "user") return erpnext.entity.user(value, { size: 18 });
		return esc(["allow", "applicable_for", "role"].includes(key) ? __(value) : value);
	};

	const list_html = (values, css) =>
		items(values).length
			? items(values)
					.map((item) => `<span class="indicator-pill no-indicator-dot ${css}">${esc(item)}</span>`)
					.join(" ")
			: `<span class="text-muted">—</span>`;

	const table_rows = (doc) => {
		const { from, to } = parse(doc);
		const keys = [...new Set([...Object.keys(from), ...Object.keys(to)])].sort(
			(a, b) =>
				(KEY_ORDER.indexOf(a) + 1 || 999) - (KEY_ORDER.indexOf(b) + 1 || 999) || a.localeCompare(b)
		);
		const role = !from.role && !to.role && docperm_roles[doc.reference];
		const rows = keys
			.filter((key) => {
				if (Array.isArray(from[key]) || Array.isArray(to[key]))
					return items(from[key]).length || items(to[key]).length;
				if (is_flag(key)) return Number(from[key]) || Number(to[key]);
				return !is_empty(from[key]) || !is_empty(to[key]);
			})
			.map((key) =>
				Array.isArray(from[key]) || Array.isArray(to[key])
					? [label(key), list_html(from[key], "red"), list_html(to[key], "green")]
					: [label(key), value_html(key, from[key]), value_html(key, to[key])]
			);
		return role ? [[__("Role"), esc(__(role)), esc(__(role))], ...rows] : rows;
	};

	const table_html = (doc) => {
		const rows = table_rows(doc);
		if (!rows.length) return `<div class="text-muted">${__("No changes")}</div>`;
		return `<table class="table table-bordered permission-log-table">
			<thead><tr><th>${__("Field")}</th><th>${__("Before Change")}</th><th>${__("After Change")}</th></tr></thead>
			<tbody>${rows
				.map(
					([name, before, after]) =>
						`<tr><td>${esc(
							name
						)}</td><td class="diff-remove">${before}</td><td class="diff-add">${after}</td></tr>`
				)
				.join("")}</tbody>
		</table>`;
	};

	return { parse, current, describe, object_link, object_html, load_roles, users_of, table_html };
})();
