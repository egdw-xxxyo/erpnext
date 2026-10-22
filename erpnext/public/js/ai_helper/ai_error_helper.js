frappe.provide("erpnext.ai_helper");

erpnext.ai_helper.status = () => {
	if (!erpnext.ai_helper._status) {
		erpnext.ai_helper._status = frappe
			.xcall("erpnext.ai_helper.api.get_status")
			.then((r) => !!(r && r.available))
			.catch(() => false)
			.then((available) => {
				erpnext.ai_helper._available = available;
				return available;
			});
	}
	return erpnext.ai_helper._status;
};

erpnext.ai_helper.when_available = (fn) => {
	if (erpnext.ai_helper._available === true) return fn();
	if (erpnext.ai_helper._available === false) return;
	erpnext.ai_helper.status().then((available) => available && fn());
};

erpnext.ai_helper.CSS = `
.aih-panel { position: fixed; right: 20px; bottom: 20px; width: 400px; max-width: calc(100vw - 24px);
	height: 520px; max-height: calc(100vh - 40px); z-index: 2100; display: flex; flex-direction: column;
	background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--border-radius-lg);
	box-shadow: var(--shadow-lg); color: var(--text-color); }
.aih-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;
	border-bottom: 1px solid var(--border-color); font-weight: 600; }
.aih-head .aih-close { cursor: pointer; color: var(--text-muted); }
.aih-thread { flex: 1; overflow-y: auto; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.aih-msg { max-width: 92%; padding: 8px 12px; border-radius: var(--border-radius-md); font-size: var(--text-md);
	word-break: break-word; }
.aih-msg.user { align-self: flex-end; background: var(--control-bg); }
.aih-msg.assistant { align-self: flex-start; border: 1px solid var(--border-color); }
.aih-msg.error { align-self: flex-start; color: var(--red-600); border: 1px solid var(--red-200); }
.aih-msg.assistant p:last-child, .aih-msg.assistant ul:last-child, .aih-msg.assistant ol:last-child { margin-bottom: 0; }
.aih-msg.assistant pre { white-space: pre-wrap; }
.aih-wait { color: var(--text-muted); }
.aih-form { display: flex; gap: 8px; padding: 10px 14px; border-top: 1px solid var(--border-color); }
.aih-form textarea { flex: 1; resize: none; height: 38px; }
`;

erpnext.ai_helper.ensure_css = () => {
	if (!document.getElementById("aih-css")) {
		$(`<style id="aih-css">${erpnext.ai_helper.CSS}</style>`).appendTo(document.head);
	}
};

erpnext.ai_helper.Chat = class {
	constructor(context) {
		erpnext.ai_helper.ensure_css();
		this.context = context;
		this.messages = [];
		this.busy = false;
		this.render();
		this.send(__("Explain why this error happened and how to fix it"));
	}

	render() {
		this.$el = $(`
			<div class="aih-panel">
				<div class="aih-head">
					<span><i class="fa fa-magic"></i> ${__("AI helper")}</span>
					<i class="fa fa-times aih-close"></i>
				</div>
				<div class="aih-thread"></div>
				<div class="aih-form">
					<textarea class="form-control input-sm" placeholder="${__("Ask a follow-up question")}"></textarea>
					<button class="btn btn-primary btn-sm aih-send"><i class="fa fa-paper-plane"></i></button>
				</div>
			</div>`).appendTo(document.body);
		this.$thread = this.$el.find(".aih-thread");
		this.$input = this.$el.find("textarea");
		this.$el.find(".aih-close").on("click", () => this.close());
		this.$el.find(".aih-send").on("click", () => this.submit());
		this.$input.on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.submit();
			}
		});
	}

	submit() {
		const text = this.$input.val().trim();
		if (!text || this.busy) return;
		this.$input.val("");
		this.send(text);
	}

	add(role, html) {
		const $m = $(`<div class="aih-msg ${role}"></div>`).html(html).appendTo(this.$thread);
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		return $m;
	}

	send(text) {
		this.busy = true;
		this.messages.push({ role: "user", content: text });
		this.add("user", frappe.utils.escape_html(text).replace(/\n/g, "<br>"));
		const $wait = this.add(
			"assistant aih-wait",
			`<i class="fa fa-spinner fa-spin"></i> ${__("Thinking...")}`
		);
		frappe
			.xcall("erpnext.ai_helper.api.chat", {
				messages: this.messages,
				context: this.context,
			})
			.then((r) => {
				$wait.remove();
				if (r.ok) {
					this.messages.push({ role: "assistant", content: r.reply });
					this.add("assistant", frappe.markdown(r.reply));
				} else {
					this.messages.pop();
					this.add("error", frappe.utils.escape_html(r.error));
				}
			})
			.catch(() => {
				$wait.remove();
				this.messages.pop();
				this.add("error", __("The AI helper is unavailable right now."));
			})
			.finally(() => {
				this.busy = false;
				this.$input.trigger("focus");
			});
	}

	close() {
		this.$el.remove();
		if (erpnext.ai_helper.chat === this) erpnext.ai_helper.chat = null;
	}
};

erpnext.ai_helper.open = (error, title) => {
	if (erpnext.ai_helper.chat) erpnext.ai_helper.chat.close();
	erpnext.ai_helper.chat = new erpnext.ai_helper.Chat({
		url: window.location.href,
		route: frappe.get_route_str(),
		title: title || "",
		error: error,
	});
};

erpnext.ai_helper.attach = (dialog, get_error, get_title) => {
	const $footer = dialog.footer;
	let $btn = $footer.find(".aih-btn");
	if (!$btn.length) {
		$btn = $(
			`<button class="btn btn-default btn-sm aih-btn"><i class="fa fa-magic"></i> ${__("AI")}</button>`
		)
			.css("margin-right", "auto")
			.prependTo($footer);
	}
	$btn.off("click").on("click", () => erpnext.ai_helper.open(get_error(), get_title && get_title()));
	$footer.removeClass("hide");
	return $btn;
};

erpnext.ai_helper.install = () => {
	const msgprint = frappe.msgprint;
	frappe.msgprint = function (msg) {
		const dialog = msgprint.apply(this, arguments);
		if (!dialog || !dialog.footer) return dialog;
		const indicator = $.isPlainObject(msg) ? msg.indicator : null;
		const is_error = indicator === "red" || indicator === "orange";
		dialog.footer.find(".aih-btn").addClass("hide");
		if (is_error) {
			erpnext.ai_helper.when_available(() =>
				erpnext.ai_helper
					.attach(
						dialog,
						() => dialog.msg_area.text().trim(),
						() => dialog.$wrapper.find(".modal-title").text().trim()
					)
					.removeClass("hide")
			);
		}
		return dialog;
	};

	const report_error = frappe.request.report_error;
	frappe.request.report_error = function () {
		const result = report_error.apply(this, arguments);
		const dialog = frappe.error_dialog;
		if (dialog && dialog.footer) {
			erpnext.ai_helper.when_available(() =>
				erpnext.ai_helper.attach(
					dialog,
					() => dialog.$body.text().trim(),
					() => __("Server Error")
				)
			);
		}
		return result;
	};
};

erpnext.ai_helper.install();
$(() => erpnext.ai_helper.status());
