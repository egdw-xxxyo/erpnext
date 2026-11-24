// Центр імпорту: файл → розпізнавання скрипту → перегляд → що зміниться → імпорт.

const IMPORT_CENTER = "erpnext.import_center.engine";

frappe.pages["data-import-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Import Center"),
		single_column: true,
	});
	const state = { run: null, data: null };
	const $body = $(`<div class="import-center" style="padding: 12px 0"></div>`).appendTo(page.main);

	page.set_secondary_action(__("New Import"), () => reset(), "refresh");

	frappe.realtime.on("import_center_progress", (msg) => {
		if (!state.run || msg.run !== state.run) return;
		if (msg.failed) return load();
		if (msg.percent !== undefined) set_bar(msg.stage, msg.percent, msg.message);
		if (msg.done) load();
	});

	reset();

	function esc(text) {
		return frappe.utils.escape_html(text == null ? "" : String(text));
	}

	function reset() {
		state.run = null;
		state.data = null;
		render_upload();
	}

	function render_upload(message) {
		$body.html(`
			<div class="ic-card" style="max-width: 640px">
				<p class="text-muted">${__("Upload a file: the system recognises its type and picks the import script.")}</p>
				${message ? `<div class="alert alert-warning">${esc(message)}</div>` : ""}
				<button class="btn btn-primary btn-sm ic-upload"><i class="fa fa-upload"></i> ${__("Choose File")}</button>
			</div>`);
		$body.find(".ic-upload").on("click", pick_file);
	}

	function pick_file() {
		new frappe.ui.FileUploader({
			doctype: "Import Run",
			make_attachments_public: false,
			restrictions: { allowed_file_types: [".pdf", ".xlsx", ".csv"] },
			disable_file_browser: true,
			on_success: (file) => register(file.file_url),
		});
	}

	function register(file_url, script) {
		frappe
			.call({ method: `${IMPORT_CENTER}.register_upload`, args: { file_url, script }, freeze: true })
			.then(({ message }) => {
				if (!message.candidates.length) return render_upload(message.message);
				if (!message.run) return render_choice(message);
				state.run = message.run;
				load();
			});
	}

	function render_choice(message) {
		const rows = message.candidates
			.map(
				(c) =>
					`<button class="btn btn-default btn-sm ic-pick" data-script="${esc(
						c.name
					)}" style="display:block;margin-bottom:6px">${esc(c.title)}</button>`
			)
			.join("");
		$body.html(`<p>${__("Several scripts match this file. Choose one:")}</p>${rows}`);
		$body.find(".ic-pick").on("click", function () {
			register(message.file_url, this.dataset.script);
		});
	}

	function load() {
		frappe.call({ method: `${IMPORT_CENTER}.get_run`, args: { run: state.run } }).then(({ message }) => {
			state.data = message;
			render(message);
		});
	}

	function bar(stage, label) {
		return `<div class="ic-bar" data-stage="${stage}" style="margin:10px 0">
			<div class="small text-muted ic-bar-text">${label}</div>
			<div class="progress" style="height:10px"><div class="progress-bar" style="width:0%"></div></div>
		</div>`;
	}

	function set_bar(stage, percent, message) {
		const $bar = $body.find(`.ic-bar[data-stage="${stage}"]`);
		$bar.find(".progress-bar").css("width", `${cint(percent)}%`);
		if (message) $bar.find(".ic-bar-text").text(message);
	}

	function render(data) {
		const script = data.script;
		const head = `
			<h4>${esc(script.title)}</h4>
			${script.description ? `<p class="text-muted">${esc(script.description)}</p>` : ""}`;
		const missing = script.missing_permissions || [];

		if (missing.length) {
			return $body.html(`${head}<div class="alert alert-danger">
				<b>${__("You cannot import this file")}</b> — ${__("missing permissions")}:
				<ul>${missing.map((m) => `<li>${esc(__(m.ptype))} · ${esc(__(m.doctype))}</li>`).join("")}</ul></div>`);
		}

		if (data.status === "Uploaded") {
			$body.html(`${head}${change_fields_html(script)}
				<button class="btn btn-primary btn-sm ic-parse">${__("Read the File")}</button>`);
			return $body.find(".ic-parse").on("click", start_parse);
		}

		if (data.status === "Parsing") {
			$body.html(`${head}${bar("parse", __("Reading the file"))}`);
			return set_bar("parse", data.progress, data.stage);
		}

		if (data.status === "Importing") {
			$body.html(`${head}${bar("import", __("Importing"))}`);
			return set_bar("import", data.progress, data.stage);
		}

		if (data.status === "Failed") {
			return $body
				.html(
					`${head}<div class="alert alert-danger">${esc(data.error)}</div>
				<button class="btn btn-default btn-sm ic-retry">${__("Try Again")}</button>`
				)
				.find(".ic-retry")
				.on("click", reset);
		}

		if (data.status === "Done") {
			const stats = Object.entries(data.stats || {})
				.map(([k, v]) => `<li>${esc(__(k))}: <b>${esc(v)}</b></li>`)
				.join("");
			return $body.html(
				`${head}<div class="alert alert-success">${__("Import finished")}</div><ul>${stats}</ul>`
			);
		}

		render_parsed(data, head);
	}

	function change_fields_html(script) {
		if (!script.change_fields.length) return "";
		return `<p class="text-muted" style="margin-top:12px">${__(
			"Fields that will change"
		)}:</p><ul>${script.change_fields
			.map(
				(f) =>
					`<li>${esc(__(f.doctype))} → ${esc(__(f.label))} <span class="text-muted">(${esc(
						__(f.mode)
					)})</span></li>`
			)
			.join("")}</ul>`;
	}

	function start_parse() {
		frappe.call({ method: `${IMPORT_CENTER}.start_parse`, args: { run: state.run } }).then(() => {
			$body.html(bar("parse", __("Reading the file")));
			load();
		});
	}

	function render_parsed(data, head) {
		const parsed = data.parsed || {};
		const sections = (data.script.preview_config || {}).sections || [];
		const warnings = (parsed.warnings || [])
			.map((w) => `<div class="alert alert-warning" style="margin-bottom:6px">${esc(w)}</div>`)
			.join("");
		const preview = sections.map((s) => section_html(s, parsed)).join("");
		const plan = plan_html(data.plan || []);
		const changes = (data.plan || []).reduce((n, i) => n + (i.changes || []).length, 0);
		const blocked = (data.plan || []).some((i) => !i.name);

		$body.html(`${head}${warnings}${preview}${plan}
			<div style="margin-top:14px">
				<button class="btn btn-primary btn-sm ic-import" ${changes && !blocked ? "" : "disabled"}>
					<i class="fa fa-check"></i> ${__("Import")}${changes ? ` (${changes})` : ""}</button>
			</div>${bar("import", __("Importing"))}`);
		$body.find(".ic-bar[data-stage=import]").hide();
		$body.find(".ic-import").on("click", () => start_import(data));
	}

	function start_import(data) {
		$body.find(".ic-import").prop("disabled", true);
		$body.find(".ic-bar[data-stage=import]").show();
		frappe
			.call({
				method: `${IMPORT_CENTER}.start_import`,
				args: { run: state.run, plan_hash: data.plan_hash },
			})
			.catch(() => load());
	}

	function section_html(section, parsed) {
		const source = parsed[section.source];
		const title = section.title ? `<h6 style="margin-top:14px">${esc(__(section.title))}</h6>` : "";

		if (section.kind === "key_value") {
			return `${title}<table class="table table-bordered table-sm" style="max-width:560px">${(
				section.columns || Object.keys(source || {})
			)
				.map((c) => {
					const key = typeof c === "string" ? c : c.key;
					const label = typeof c === "string" ? c : c.label;
					return `<tr><td class="text-muted" style="width:45%">${esc(__(label))}</td><td>${esc(
						(source || {})[key]
					)}</td></tr>`;
				})
				.join("")}</table>`;
		}

		if (section.kind === "grid") {
			const rows = source || [];
			const years = [...new Set(rows.map((r) => r.year))].sort();
			const cell = (y, m) => (rows.find((r) => r.year === y && r.month === m) || {}).days;
			return `${title}<div style="overflow-x:auto"><table class="table table-bordered table-sm" style="font-size:12px">
				<tr><th></th>${[...Array(12).keys()].map((m) => `<th>${m + 1}</th>`).join("")}</tr>
				${years
					.map(
						(y) =>
							`<tr><th>${y}</th>${[...Array(12).keys()]
								.map((m) => `<td>${cell(y, m + 1) ?? ""}</td>`)
								.join("")}</tr>`
					)
					.join("")}</table></div>`;
		}

		const cols = section.columns || [];
		return `${title}<table class="table table-bordered table-sm"><tr>${cols
			.map((c) => `<th>${esc(__(c.label || c))}</th>`)
			.join("")}</tr>${(source || [])
			.slice(0, section.max_rows || 50)
			.map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c.key || c])}</td>`).join("")}</tr>`)
			.join("")}</table>`;
	}

	function plan_html(plan) {
		if (!plan.length) return "";
		return `<h6 style="margin-top:18px">${__("What will change")}</h6>${plan
			.map((item) => {
				const who = item.name
					? erpnext.entity.employee({ name: item.name, employee_name: item.label }, { size: 24 })
					: `<b>${esc(item.label)}</b>`;
				const problem = item.problem
					? `<div class="alert ${
							item.name ? "alert-warning" : "alert-danger"
					  }" style="margin:6px 0">${esc(item.problem)}</div>`
					: "";
				const rows = (item.changes || [])
					.map(
						(c) =>
							`<tr><td>${esc(c.label || c.field)}</td><td class="text-muted">${esc(
								c.old ?? "—"
							)}</td><td><b>${esc(c.new)}</b></td></tr>`
					)
					.join("");
				const table = rows
					? `<table class="table table-bordered table-sm" style="max-width:560px"><tr><th>${__(
							"Field"
					  )}</th><th>${__("Now")}</th><th>${__("Will be")}</th></tr>${rows}</table>`
					: item.name
					? `<p class="text-muted">${__("Nothing to change")}</p>`
					: "";
				const same = item.unchanged
					? `<p class="small text-muted">${__("Unchanged: {0}", [item.unchanged])}</p>`
					: "";
				return `<div style="margin-top:10px">${who}${problem}${table}${same}</div>`;
			})
			.join("")}`;
	}
};
