frappe.provide("erpnext.access_control");

erpnext.access_control.view_session = (() => {
	const END_METHOD = "erpnext.access_control.impersonation.end_view";
	const START_METHOD = "erpnext.access_control.impersonation.start_view";
	const SIMULATE_METHOD = "erpnext.access_control.dry_run.simulate";
	const SIMULATED = new Set([
		"frappe.desk.form.save.savedocs",
		"frappe.desk.form.save.cancel",
		"frappe.model.workflow.apply_workflow",
	]);
	const HISTORY_KEY = "access_view_steps";
	const READ_ONLY_TITLE = __("In Read Only Mode");

	const read_history = () => {
		try {
			return JSON.parse(sessionStorage.getItem(HISTORY_KEY) || "[]");
		} catch (e) {
			return [];
		}
	};

	const write_history = (steps) => {
		try {
			sessionStorage.setItem(HISTORY_KEY, JSON.stringify(steps));
		} catch (e) {
			return;
		}
	};

	let history = [];

	const view = () => frappe.boot && frappe.boot.access_view;

	const end = () => {
		write_history([]);
		return frappe
			.xcall(END_METHOD)
			.then(({ route }) => window.location.assign(route))
			.catch(() => window.location.assign("/login"));
	};

	const start = (user, full_name) => {
		const dialog = new frappe.ui.Dialog({
			title: __("View as {0}", [frappe.utils.escape_html(full_name || user)]),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "note",
					options: `<p class="text-muted small">${__(
						"View only: nothing you do is saved. The user gets a notification with your reason."
					)}</p>`,
				},
				{ fieldtype: "Small Text", fieldname: "reason", label: __("Reason"), reqd: 1 },
			],
			primary_action_label: __("Start viewing"),
			primary_action: ({ reason }) =>
				frappe
					.xcall(START_METHOD, { user, reason })
					.then(({ route }) => window.location.assign(route)),
		});
		dialog.show();
		return dialog;
	};

	const banner_html = (info) => `
		<div class="access-view-banner">
			<i class="fa fa-eye"></i>
			<span>${__("Viewing as {0}", [
				`<b>${frappe.utils.escape_html(frappe.session.user_fullname || frappe.session.user)}</b>`,
			])}</span>
			<span class="access-view-mode">${__("view only, nothing is saved")}</span>
			<span class="access-view-by text-muted">${__("Started by {0}", [
				frappe.utils.escape_html(info.by_name),
			])}</span>
			<span class="access-view-steps hide">
				<i class="fa fa-flask"></i> <span class="access-view-steps-label"></span>
				<a class="access-view-reset">${__("Reset")}</a>
			</span>
			<button class="btn btn-xs btn-default access-view-end">
				<i class="fa fa-sign-out"></i> ${__("Finish session")}
			</button>
		</div>`;

	const add_style = () => {
		if (document.getElementById("access-view-style")) return;
		const style = document.createElement("style");
		style.id = "access-view-style";
		style.textContent = `
			.access-view-banner {
				position: fixed;
				left: 0;
				right: 0;
				bottom: var(--margin-lg, 16px);
				width: fit-content;
				margin: 0 auto;
				z-index: 1060;
				display: flex;
				flex-wrap: wrap;
				align-items: center;
				justify-content: center;
				gap: var(--margin-sm);
				max-width: calc(100vw - 32px);
				padding: var(--padding-sm) var(--padding-md);
				background-color: var(--yellow-highlight-color, #fff7d3);
				color: var(--text-color);
				font-size: var(--text-sm);
				border: 1px solid var(--yellow-300, #f5d978);
				border-radius: var(--border-radius-lg, 12px);
				box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.15));
			}
			body.access-view .page-container { padding-bottom: 72px; }
			.access-view-mode {
				padding: 0 var(--padding-xs);
				border-radius: var(--border-radius-full);
				background-color: var(--bg-orange, #fff0e1);
				font-size: var(--text-xs);
			}
			.access-view-steps {
				display: inline-flex;
				align-items: center;
				gap: 4px;
				font-size: var(--text-xs);
			}
			.access-view-steps.hide { display: none; }
			.access-view-reset { cursor: pointer; text-decoration: underline; }
			body.access-view .read-only-banner,
			body.access-view .page-actions > .indicator-pill.red {
				display: none !important;
			}
		`;
		document.head.appendChild(style);
	};

	const show_banner = (info) => {
		add_style();
		document.body.classList.add("access-view");
		const $banner = $(banner_html(info)).prependTo("body");
		$banner.find(".access-view-end").on("click", end);
		$banner.find(".access-view-reset").on("click", reset);
	};

	const render_steps = () => {
		const $steps = $(".access-view-steps");
		$steps.toggleClass("hide", !history.length);
		$steps
			.find(".access-view-steps-label")
			.text(__("Simulated steps: {0}, nothing saved", [history.length]));
	};

	const reset = () => {
		history = [];
		write_history(history);
		render_steps();
		frappe.show_alert({ message: __("Simulation reset, data is shown as saved"), indicator: "blue" });
		const frm = window.cur_frm;
		if (frm && !frm.is_new()) frm.reload_doc();
	};

	const normalize = (opts, args, callback) =>
		typeof opts === "string" ? { method: opts, args, callback } : opts;

	const simulated = (opts) => {
		const step = { method: opts.method, args: JSON.parse(JSON.stringify(opts.args || {})) };
		const callback = opts.callback;
		return {
			...opts,
			method: SIMULATE_METHOD,
			args: { steps: JSON.stringify([...history, step]) },
			callback: (r) => {
				if (!r.exc) {
					history = [...history, { ...step, names: (r.dry_run && r.dry_run.names) || [] }];
					write_history(history);
					render_steps();
					frappe.show_alert({ message: __("Simulated, nothing was saved"), indicator: "orange" });
				}
				return callback && callback(r);
			},
		};
	};

	const intercept_calls = () => {
		const call = frappe.call;
		frappe.call = function (opts, args, callback) {
			const options = normalize(opts, args, callback);
			return call.call(this, SIMULATED.has(options.method) ? simulated(options) : options);
		};
	};

	const replace_logout = () => {
		if (frappe.app) frappe.app.logout = end;
	};

	const replace_read_only_message = () => {
		const msgprint = frappe.msgprint;
		frappe.msgprint = function (msg, title) {
			const data = $.isPlainObject(msg) ? msg : { title };
			if (data.title !== READ_ONLY_TITLE) return msgprint.apply(this, arguments);
			return msgprint.call(this, {
				title: __("View only"),
				indicator: "orange",
				message: __(
					"You are viewing the system as another user. Changes are not saved. Finish the session to return to your account."
				),
			});
		};
	};

	const setup = () => {
		const info = view();
		if (!info) return;
		history = read_history();
		show_banner(info);
		render_steps();
		intercept_calls();
		replace_logout();
		replace_read_only_message();
	};

	$(document).on("app_ready", setup);

	return { start, end, reset };
})();
