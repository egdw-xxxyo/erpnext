import frappe
from frappe import _
from frappe.utils import flt

NO_REQUESTS = "Немає запитів на оплату"
UNPAID_REQUESTS = "Є неоплачені запити"
PAID = "Оплачено"
FORM_CLIENT_SCRIPT_NAME = "Payments: оплати за завданням"
LIST_CLIENT_SCRIPT_NAME = "Payments: стан оплати завдань"


FORM_CLIENT_SCRIPT = r"""
frappe.ui.form.on("Task", {
	refresh(frm) {
		if (frm.is_new()) return;
		payments_setup_dependency_grid(frm);

		frm.add_custom_button(__("Purchase Invoice"), () => {
			frappe.new_doc("Purchase Invoice", {
				custom_task: frm.doc.name,
				project: frm.doc.project || undefined,
			});
		}, __("Create"));

		frm.add_custom_button(__("Payment Request"), () => {
			payments_create_request(frm);
		}, __("Create"));

		frm.add_custom_button(__("Material Request"), () => {
			frappe.new_doc("Material Request", {
				material_request_type: "Material Transfer",
				custom_task: frm.doc.name,
			});
		}, __("Create"));

		payments_render_overview(frm);
	},
});

function payments_create_request(frm) {
	frappe.call({
		method: "erpnext.projects.task_payments.get_available_purchase_invoices",
		args: { task: frm.doc.name },
	}).then((response) => {
		const invoices = response.message || [];
		if (!invoices.length) {
			frappe.msgprint({
				title: __("No Available Invoices"),
				indicator: "orange",
				message: __("Create and submit a Purchase Invoice for this task first."),
			});
			return;
		}

		const options = invoices.map((row) => row.name);
		const dialog = new frappe.ui.Dialog({
			title: __("Create Payment Request"),
			fields: [{
				fieldname: "purchase_invoice",
				fieldtype: "Select",
				label: __("Purchase Invoice"),
				options,
				reqd: 1,
				description: invoices.map((row) =>
					`${frappe.utils.escape_html(row.name)} — ${format_currency(row.outstanding_amount, row.currency)}`
				).join("<br>"),
			}],
			primary_action_label: __("Create"),
			primary_action(values) {
				dialog.disable_primary_action();
				frappe.call({
					method: "erpnext.projects.task_payments.create_payment_request",
					args: {
						task: frm.doc.name,
						purchase_invoice: values.purchase_invoice,
					},
				}).then((result) => {
					dialog.hide();
					frappe.set_route("Form", "Payment Request", result.message);
				}).catch(() => dialog.enable_primary_action());
			},
		});
		dialog.show();
	});
}

function payments_render_overview(frm) {
	const paymentField = frm.get_field("custom_payment_requests_html");
	const materialField = frm.get_field("custom_material_requests_html");
	if (!paymentField && !materialField) return;

	frappe.call({
		method: "erpnext.projects.task_payments.get_task_payment_overview",
		args: { task: frm.doc.name },
	}).then((response) => {
		const data = response.message || {};
		if (paymentField) paymentField.$wrapper.html(payments_overview_html(data));
		if (materialField) materialField.$wrapper.html(payments_material_requests_html(data));
	});
}

function payments_material_requests_html(data) {
	const requests = data.material_requests || [];
	let html = `<div><h5>${__("Material Requests for This Task")}</h5>`;
	if (!requests.length) {
		return `${html}<div class="text-muted small">${__("There are no Material Requests yet.")}</div></div>`;
	}

	html += `<div class="table-responsive"><table class="table table-bordered table-sm">
		<thead><tr><th>${__("Request")}</th><th>${__("Status")}</th><th class="text-right">${__("Material Cost")}</th></tr></thead><tbody>`;
	for (const row of requests) {
		html += `<tr>
			<td><a href="/app/material-request/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.name)}</a></td>
			<td>${payments_material_request_status_badge(row.status)}</td>
			<td class="text-right">${format_currency(row.total, row.currency)}</td>
		</tr>`;
	}
	return `${html}</tbody></table></div></div>`;
}

function payments_material_request_status_badge(status) {
	const colours = {
		"Draft": "red",
		"Submitted": "blue",
		"Stopped": "red",
		"Cancelled": "red",
		"Pending": "orange",
		"Partially Ordered": "yellow",
		"Partially Received": "yellow",
		"Ordered": "green",
		"Issued": "green",
		"Transferred": "green",
		"Received": "green",
	};
	const value = status || "Draft";
	return `<span class="indicator-pill ${colours[value] || "gray"}">${frappe.utils.escape_html(__(value))}</span>`;
}

function payments_overview_html(data) {
	const requests = data.requests || [];
	const children = data.children || [];
	let html = `<div class="mb-4"><h5>${__("Payment Requests for This Task")}</h5>`;

	if (!requests.length) {
		html += `<div class="text-muted small">${__("There are no Payment Requests yet.")}</div>`;
	} else {
		html += `<div class="table-responsive"><table class="table table-bordered table-sm">
			<thead><tr><th>${__("Request")}</th><th>${__("Short Description")}</th><th>${__("Approval Stage")}</th><th class="text-right">${__("Amount")}</th></tr></thead><tbody>`;
		for (const row of requests) {
			html += `<tr>
				<td><a href="/app/payment-request/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.name)}</a></td>
				<td>${payments_short_description(row.short_description)}</td>
				<td>${payments_workflow_badge(row.workflow_state)}</td>
				<td class="text-right">${format_currency(row.grand_total, row.currency)}</td>
			</tr>`;
		}
		html += `</tbody></table></div>`;
	}
	html += `</div>`;

	if (children.length) {
		html += `<div><h5>${__("Child Task Payments")}</h5>
			<div class="table-responsive"><table class="table table-bordered table-sm">
			<thead><tr><th>${__("Task")}</th><th>${__("Payment Status")}</th><th class="text-right">${__("Expenses")}</th></tr></thead><tbody>`;
		for (const row of children) {
			html += `<tr>
				<td><a href="/app/task/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(row.subject || row.name)}</a></td>
				<td>${payments_status_badge(row.payment_status)}</td>
				<td class="text-right">${format_currency(row.total, row.currency)}</td>
			</tr>`;
		}
		html += `</tbody></table></div></div>`;
	}

	return html;
}

function payments_short_description(description) {
	const value = String(description || "").trim() || __("No Description");
	const escaped = frappe.utils.escape_html(value);
	return `<div class="ellipsis" style="max-width: 360px" title="${escaped}">${escaped}</div>`;
}

function payments_status_badge(status) {
	const colours = {
		"Оплачено": "green",
		"Є неоплачені запити": "red",
		"Немає запитів на оплату": "gray",
	};
	const value = status || "Немає запитів на оплату";
	return `<span class="indicator-pill ${colours[value] || "gray"}">${frappe.utils.escape_html(__(value))}</span>`;
}

function payments_workflow_badge(state) {
	const colours = {
		"Чернетка": "blue",
		"Перевірка підрозділу": "orange",
		"Фінальне погодження": "orange",
		"Перевірка казначейства": "light-blue",
		"Потребує доопрацювання": "red",
		"Погоджено": "green",
		"Відхилено": "red",
	};
	const value = state || "—";
	return `<span class="indicator-pill ${colours[value] || "gray"}">${frappe.utils.escape_html(__(value))}</span>`;
}

function payments_setup_dependency_grid(frm) {
	const grid = frm.get_field("depends_on")?.grid;
	if (!grid?.get_field("custom_payment_status")) return;
	grid.refresh();
	setTimeout(() => {
		for (const row of grid.grid_rows || []) {
			const taskColumn = row.columns?.task;
			if (taskColumn?.static_area && row.doc?.task) {
				const taskName = row.doc.task;
				const taskLink = $(`<a class="payments-task-link" href="/app/task/${encodeURIComponent(taskName)}"></a>`)
					.text(taskName)
					.on("click", (event) => {
						event.preventDefault();
						event.stopImmediatePropagation();
						frappe.set_route("Form", "Task", taskName);
					});
				taskColumn.static_area.empty().append(taskLink);
			}
			const statusColumn = row.columns?.custom_payment_status;
			if (statusColumn?.static_area && row.doc) {
				statusColumn.static_area.html(payments_status_badge(row.doc.custom_payment_status));
			}
		}
	}, 0);
}
""".strip()


LIST_CLIENT_SCRIPT = r"""
const taskListSettings = frappe.listview_settings["Task"] || {};
taskListSettings.total_fields = 6;
taskListSettings.formatters = taskListSettings.formatters || {};
taskListSettings.formatters.custom_payment_status = function (value) {
	const status = value || "Немає запитів на оплату";
	const colours = {
		"Оплачено": "green",
		"Є неоплачені запити": "red",
		"Немає запитів на оплату": "gray",
	};
	const escaped = frappe.utils.escape_html(status);
	return `<span class="filterable indicator-pill ${colours[status] || "gray"} ellipsis"
		data-filter="custom_payment_status,=,${escaped}"><span class="ellipsis">${__(status)}</span></span>`;
};
frappe.listview_settings["Task"] = taskListSettings;
""".strip()


def set_payment_request_task(doc, method=None):
	"""Copy the business Task link from the accounting source document."""
	if doc.reference_doctype != "Purchase Invoice" or not doc.reference_name:
		return

	task = frappe.db.get_value("Purchase Invoice", doc.reference_name, "custom_task")
	if task:
		doc.custom_task = task


def validate_payment_request_short_description(doc, method=None):
	description = doc.get("custom_short_description") or ""
	if len(description) > 255:
		frappe.throw(_("The short description cannot contain more than 255 characters."))


def sync_payment_request_task_summary(doc, method=None):
	task = doc.get("custom_task")
	if not task:
		before = doc.get_doc_before_save()
		task = before.get("custom_task") if before else None
	if task:
		sync_task_and_ancestors(task)


def sync_payment_entry_task_summaries(doc, method=None):
	requests = frappe.get_all(
		"Payment Entry Reference",
		filters={"parent": doc.name, "payment_request": ["is", "set"]},
		pluck="payment_request",
	)
	tasks = (
		frappe.get_all(
			"Payment Request",
			filters={"name": ["in", requests], "custom_task": ["is", "set"]},
			pluck="custom_task",
		)
		if requests
		else []
	)
	for task in set(tasks):
		sync_task_and_ancestors(task)


def sync_task_hierarchy_summary(doc, method=None):
	if method == "after_delete":
		if doc.get("parent_task"):
			sync_task_and_ancestors(doc.parent_task)
		return
	if not doc.name:
		return
	sync_task_and_ancestors(doc.name)
	before = doc.get_doc_before_save()
	old_parent = before.get("parent_task") if before else None
	if old_parent and old_parent != doc.get("parent_task"):
		sync_task_and_ancestors(old_parent)


def sync_task_and_ancestors(task):
	targets = _task_and_ancestors(task)
	dependency_groups = frappe.get_all(
		"Task Depends On",
		filters={"task": task, "parenttype": "Task"},
		pluck="parent",
	)
	for group in dependency_groups:
		for task_name in _task_and_ancestors(group):
			if task_name not in targets:
				targets.append(task_name)
	for task_name in targets:
		_update_task_summary(task_name)


def sync_all_task_summaries():
	if not frappe.db.has_column("Task", "custom_payment_status"):
		return
	for task in frappe.get_all("Task", order_by="rgt asc", pluck="name"):
		_update_task_summary(task)


def _update_task_summary(task):
	if not frappe.db.exists("Task", task):
		return
	task_names = _task_with_descendants(task)
	requests = _get_requests(task_names)
	status = (
		NO_REQUESTS
		if not requests
		else (PAID if all(row.status == "Paid" for row in requests) else UNPAID_REQUESTS)
	)
	total = sum(_request_company_amount(row) for row in requests)
	currency = _get_task_currency(task)
	frappe.db.set_value(
		"Task",
		task,
		{
			"custom_payment_request_count": len(requests),
			"custom_payment_request_total": total,
			"custom_payment_status": status,
			"custom_payment_currency": currency,
		},
		update_modified=False,
	)
	frappe.db.set_value(
		"Task Depends On",
		{"task": task},
		{
			"custom_payment_request_total": total,
			"custom_payment_status": status,
		},
		update_modified=False,
	)


def _task_and_ancestors(task):
	result = []
	seen = set()
	current = task
	while current and current not in seen:
		seen.add(current)
		result.append(current)
		current = frappe.db.get_value("Task", current, "parent_task")
	return result


def _task_with_descendants(task):
	bounds = frappe.db.get_value("Task", task, ["lft", "rgt"], as_dict=True)
	if not bounds or bounds.lft is None or bounds.rgt is None:
		return [task]
	tasks = frappe.get_all(
		"Task",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
	) or [task]
	if frappe.db.get_value("Task", task, "is_group"):
		members = frappe.get_all(
			"Task Depends On",
			filters={"parent": task, "parenttype": "Task"},
			pluck="task",
		)
		for member in members:
			member_bounds = frappe.db.get_value("Task", member, ["lft", "rgt"], as_dict=True)
			if member_bounds and member_bounds.lft is not None and member_bounds.rgt is not None:
				tasks.extend(
					frappe.get_all(
						"Task",
						filters={"lft": [">=", member_bounds.lft], "rgt": ["<=", member_bounds.rgt]},
						pluck="name",
					)
				)
			else:
				tasks.append(member)
	return list(dict.fromkeys(tasks))


def _get_requests(tasks):
	if not tasks:
		return []
	return frappe.get_all(
		"Payment Request",
		filters={"custom_task": ["in", tasks], "docstatus": ["<", 2]},
		fields=[
			"name",
			"custom_task",
			"custom_short_description",
			"workflow_state",
			"status",
			"grand_total",
			"currency",
			"reference_doctype",
			"reference_name",
		],
		order_by="creation desc",
	)


def _request_company_amount(request):
	amount = flt(request.grand_total)
	if request.reference_doctype != "Purchase Invoice" or not request.reference_name:
		return amount
	conversion_rate = frappe.db.get_value("Purchase Invoice", request.reference_name, "conversion_rate") or 1
	return amount * flt(conversion_rate)


def _get_task_currency(task):
	project = frappe.db.get_value("Task", task, "project")
	company = frappe.db.get_value("Project", project, "company") if project else None
	return frappe.get_cached_value("Company", company, "default_currency") if company else None


def _get_material_requests(task):
	requests = frappe.get_list(
		"Material Request",
		filters={"custom_task": task, "docstatus": ["<", 2]},
		fields=["name", "status", "company"],
		order_by="creation desc",
	)
	if not requests:
		return []

	totals = frappe.get_all(
		"Material Request Item",
		filters={"parent": ["in", [row.name for row in requests]], "parenttype": "Material Request"},
		fields=["parent", "sum(amount) as total"],
		group_by="parent",
	)
	total_by_request = {row.parent: flt(row.total) for row in totals}
	for row in requests:
		row.total = total_by_request.get(row.name, 0)
		row.currency = frappe.get_cached_value("Company", row.company, "default_currency")
	return requests


@frappe.whitelist()
def get_task_payment_overview(task):
	task_doc = frappe.get_doc("Task", task)
	task_doc.check_permission("read")
	direct_requests = _get_requests([task])
	child_names = frappe.get_list(
		"Task",
		filters={"parent_task": task},
		pluck="name",
	)
	dependency_names = frappe.get_all(
		"Task Depends On",
		filters={"parent": task, "parenttype": "Task"},
		pluck="task",
	)
	member_names = list(dict.fromkeys(child_names + dependency_names))
	children = (
		frappe.get_list(
			"Task",
			filters={"name": ["in", member_names]},
			fields=[
				"name",
				"subject",
				"custom_payment_status as payment_status",
				"custom_payment_request_total as total",
				"custom_payment_currency as currency",
			],
			order_by="subject asc",
		)
		if member_names
		else []
	)
	return {
		"requests": [
			{
				"name": row.name,
				"short_description": row.custom_short_description,
				"workflow_state": row.workflow_state,
				"main_status": row.status,
				"grand_total": row.grand_total,
				"currency": row.currency,
			}
			for row in direct_requests
		],
		"children": children,
		"material_requests": _get_material_requests(task),
	}


@frappe.whitelist()
def get_available_purchase_invoices(task):
	frappe.get_doc("Task", task).check_permission("read")
	return frappe.get_list(
		"Purchase Invoice",
		filters={"custom_task": task, "docstatus": 1, "outstanding_amount": [">", 0]},
		fields=["name", "supplier_name", "outstanding_amount", "currency"],
		order_by="posting_date desc",
	)


@frappe.whitelist()
def create_payment_request(task, purchase_invoice):
	from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request

	frappe.get_doc("Task", task).check_permission("read")
	frappe.has_permission("Payment Request", ptype="create", throw=True)
	invoice = frappe.get_doc("Purchase Invoice", purchase_invoice)
	invoice.check_permission("read")
	if invoice.docstatus != 1 or invoice.custom_task != task:
		frappe.throw(_("Select a submitted Purchase Invoice linked to this task."))

	request = make_payment_request(
		dt="Purchase Invoice",
		dn=invoice.name,
		party_type="Supplier",
		party=invoice.supplier,
		party_name=invoice.supplier_name,
		mute_email=1,
		return_doc=1,
		submit_doc=0,
	)
	request.custom_task = task
	if request.is_new():
		request.insert(ignore_permissions=True)
	else:
		request.save(ignore_permissions=True)
	return request.name


def sync_task_payment_configuration():
	_ensure_task_list_view_settings()
	_upsert_client_script(FORM_CLIENT_SCRIPT_NAME, "Form", FORM_CLIENT_SCRIPT)
	_upsert_client_script(LIST_CLIENT_SCRIPT_NAME, "List", LIST_CLIENT_SCRIPT)
	sync_all_task_summaries()
	frappe.clear_cache(doctype="Task")
	frappe.clear_cache(doctype="Purchase Invoice")
	frappe.clear_cache(doctype="Payment Request")
	frappe.clear_cache(doctype="Material Request")


def _ensure_task_list_view_settings():
	if frappe.db.exists("List View Settings", "Task"):
		doc = frappe.get_doc("List View Settings", "Task")
	else:
		doc = frappe.new_doc("List View Settings")
		doc.name = "Task"
	doc.total_fields = "6"
	doc.fields = frappe.as_json(
		[
			{"label": _("Subject"), "fieldname": "subject"},
			{"type": "Status", "label": _("Status"), "fieldname": "status_field"},
			{"label": _("Project"), "fieldname": "project"},
			{"label": _("Payment Request Expenses"), "fieldname": "custom_payment_request_total"},
			{"label": _("Payment Status"), "fieldname": "custom_payment_status"},
		]
	)
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)


def _upsert_client_script(name, view, script):
	if frappe.db.exists("Client Script", name):
		doc = frappe.get_doc("Client Script", name)
	else:
		doc = frappe.new_doc("Client Script")
		doc.name = name
	doc.dt = "Task"
	doc.view = view
	doc.enabled = 1
	doc.script = script
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.save(ignore_permissions=True)
