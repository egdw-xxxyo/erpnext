frappe.provide("erpnext.label_designer");

const LAI_FIELDS = [
	"editor_mode",
	"html_template",
	"layout_json",
	"label_size",
	"field_mapping",
	"preview_data",
	"reference_doctype",
	"template_type",
	"description",
	"padding_top_mm",
	"padding_right_mm",
	"padding_bottom_mm",
	"padding_left_mm",
];
const LAI_INPUT_FIELDS = ["fieldname", "label", "fieldtype", "options", "default_value", "reqd"];
const LAI_TOOLS = {
	get_label_template: __("Reading the label"),
	get_label_template_reference: __("Reading the label reference"),
	edit_label_template: __("Changing the label"),
	render_label_preview: __("Rendering the print preview"),
	list_label_images: __("Looking at label images"),
	get_label_image: __("Looking at an image"),
	list_label_templates: __("Looking at other templates"),
	get_other_label_template: __("Reading another template"),
	get_doctype_fields: __("Reading document fields"),
	get_documents: __("Reading documents"),
};

erpnext.label_designer.LabelAI = class LabelAI {
	constructor(frm) {
		this.frm = frm;
		this.messages = [];
		this.busy = false;
		this.on_rt = (data) => this.on_event(data);
		frappe.realtime.on("label_ai", this.on_rt);
		erpnext.ai_helper.ensure_css();
		this.inject_css();
		this.$fab = $(
			`<button class="lai-fab" title="${__("AI label assistant")}"><i class="fa fa-magic"></i></button>`
		).appendTo(document.body);
		this.$fab.on("click", () => this.toggle());
	}

	static attach(frm) {
		erpnext.ai_helper.when_available(() => {
			const cur = erpnext.label_designer._ai;
			if (cur && cur.frm === frm) return cur.$fab.show();
			if (cur) cur.destroy();
			erpnext.label_designer._ai = new LabelAI(frm);
		});
	}

	static detach() {
		const cur = erpnext.label_designer._ai;
		if (cur) cur.destroy();
		erpnext.label_designer._ai = null;
	}

	destroy() {
		frappe.realtime.off("label_ai", this.on_rt);
		this.$fab.remove();
		this.$panel && this.$panel.remove();
	}

	inject_css() {
		if (document.getElementById("lai-css")) return;
		$(`<style id="lai-css">
			.lai-fab{position:fixed;right:24px;bottom:96px;z-index:1036;width:48px;height:48px;border-radius:50%;
				border:none;background:var(--primary);color:#fff;font-size:20px;box-shadow:var(--shadow-lg);cursor:pointer}
			.lai-fab.busy{animation:lai-pulse 1.2s infinite}
			@keyframes lai-pulse{50%{opacity:.55}}
			.lai-panel{right:24px;bottom:156px;height:560px;width:420px}
			.lai-progress{font-size:var(--text-sm);color:var(--text-muted);display:flex;gap:6px;align-items:center}
			.lai-bar{display:flex;gap:6px;padding:6px 14px;border-top:1px solid var(--border-color);flex-wrap:wrap}
			.lai-hint{font-size:var(--text-sm);color:var(--text-muted)}
		</style>`).appendTo(document.head);
	}

	toggle() {
		if (!this.$panel) this.make_panel();
		this.$panel.toggle();
		if (this.$panel.is(":visible")) this.$panel.find("textarea").trigger("focus");
	}

	make_panel() {
		this.$panel = $(`
			<div class="aih-panel lai-panel">
				<div class="aih-head"><span><i class="fa fa-magic"></i> ${__("AI label assistant")}</span>
					<span class="aih-close">&times;</span></div>
				<div class="aih-thread">
					<div class="lai-hint">${__(
						"Ask for a change, e.g. “add the item name above the barcode” or “make the serial bigger and center everything”. The assistant edits the label on screen and checks the print preview; nothing is saved until you press Save."
					)}</div>
				</div>
				<div class="lai-bar" style="display:none">
					<button class="btn btn-xs btn-default lai-undo"><i class="fa fa-undo"></i> ${__("Undo AI changes")}</button>
					<button class="btn btn-xs btn-default lai-new">${__("New conversation")}</button>
				</div>
				<div class="aih-form">
					<textarea class="form-control" placeholder="${__("What should change on the label?")}"></textarea>
					<button class="btn btn-primary btn-sm lai-send"><i class="fa fa-paper-plane"></i></button>
				</div>
			</div>`).appendTo(document.body);
		this.$thread = this.$panel.find(".aih-thread");
		this.$panel.find(".aih-close").on("click", () => this.$panel.hide());
		this.$panel.find(".lai-send").on("click", () => this.send());
		this.$panel.find("textarea").on("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey) {
				e.preventDefault();
				this.send();
			}
		});
		this.$panel.find(".lai-undo").on("click", () => this.undo());
		this.$panel.find(".lai-new").on("click", () => {
			this.messages = [];
			this.$thread.find(".aih-msg").remove();
		});
	}

	add(role, html) {
		const $m = $(`<div class="aih-msg ${role}"></div>`).html(html).appendTo(this.$thread);
		this.$thread.scrollTop(this.$thread[0].scrollHeight);
		return $m;
	}

	draft() {
		const d = this.frm.doc;
		const out = {};
		LAI_FIELDS.forEach((k) => (out[k] = d[k] ?? null));
		out.inputs = (d.inputs || []).map((r) =>
			Object.fromEntries(LAI_INPUT_FIELDS.map((k) => [k, r[k] ?? null]))
		);
		return out;
	}

	async apply(draft) {
		const frm = this.frm;
		const order = LAI_FIELDS.filter((k) => k !== "editor_mode" && k !== "html_template");
		for (const k of order) {
			if (k in draft && (frm.doc[k] ?? null) !== (draft[k] ?? null)) await frm.set_value(k, draft[k]);
		}
		if (draft.editor_mode && draft.editor_mode !== frm.doc.editor_mode) {
			await frm.set_value("editor_mode", draft.editor_mode);
		}
		if (
			draft.editor_mode !== "Visual" &&
			"html_template" in draft &&
			draft.html_template !== frm.doc.html_template
		) {
			await frm.set_value("html_template", draft.html_template);
		}
		if (Array.isArray(draft.inputs)) {
			const now = JSON.stringify(this.draft().inputs);
			if (now !== JSON.stringify(draft.inputs)) {
				frm.clear_table("inputs");
				draft.inputs.forEach((r) => frm.add_child("inputs", r));
				frm.refresh_field("inputs");
				frm.dirty();
			}
		}
		if (frm._designer) frm._designer.reload_from_doc();
		frm.trigger("render_preview");
	}

	send() {
		if (this.busy) return;
		const $ta = this.$panel.find("textarea");
		const text = ($ta.val() || "").trim();
		if (!text) return;
		$ta.val("");
		this.add("user", frappe.utils.escape_html(text).replace(/\n/g, "<br>"));
		this.messages.push({ role: "user", content: text });
		if (!this.snapshot) this.snapshot = this.draft();
		this.run_id = frappe.utils.get_random(12);
		this.busy = true;
		this.$fab.addClass("busy");
		this.$progress = this.add(
			"assistant",
			`<div class="lai-progress"><i class="fa fa-spinner fa-spin"></i> <span>${__(
				"Thinking..."
			)}</span></div>`
		);
		frappe
			.xcall("erpnext.devices.label_ai.start", {
				label_template: this.frm.doc.name,
				messages: JSON.stringify(this.messages),
				draft: JSON.stringify(this.draft()),
				run_id: this.run_id,
			})
			.then((r) => {
				if (!r || !r.ok) this.finish_error((r && r.error) || __("The label assistant failed."));
			})
			.catch(() => this.finish_error(__("The label assistant failed.")));
	}

	on_event(data) {
		if (!data || data.run_id !== this.run_id) return;
		if (data.type === "tool") {
			this.$progress && this.$progress.find("span").text(LAI_TOOLS[data.tool] || data.tool);
		} else if (data.type === "status") {
			this.add("assistant", frappe.markdown(data.text || ""));
			this.$progress && this.$progress.appendTo(this.$thread);
		} else if (data.type === "draft") {
			this.apply(data.draft);
			this.$panel.find(".lai-bar").show();
		} else if (data.type === "done") {
			if (data.draft) this.apply(data.draft);
			this.done();
			this.add("assistant", frappe.markdown(data.reply || ""));
			this.messages.push({ role: "assistant", content: data.reply || "" });
		} else if (data.type === "error") {
			this.finish_error(data.error);
		}
	}

	done() {
		this.busy = false;
		this.$fab.removeClass("busy");
		this.$progress && this.$progress.remove();
		this.$progress = null;
	}

	finish_error(message) {
		this.done();
		this.add("error", frappe.utils.escape_html(message));
		this.messages.pop();
	}

	undo() {
		if (!this.snapshot) return;
		this.apply(this.snapshot).then(() => {
			frappe.show_alert({ message: __("AI changes undone"), indicator: "blue" });
			this.snapshot = null;
			this.$panel.find(".lai-bar").hide();
		});
	}
};

frappe.router.on("change", () => {
	const route = frappe.get_route();
	if (!(route[0] === "Form" && route[1] === "Label Template")) erpnext.label_designer.LabelAI.detach();
});
