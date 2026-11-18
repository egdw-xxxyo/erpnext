frappe.listview_settings["Sick Leave Case"] = {
	add_fields: ["status", "closed", "fund_days"],
	get_indicator(doc) {
		const colors = {
			Open: "orange",
			Closed: "blue",
			"Employer Paid": "yellow",
			"Fund Received": "purple",
			Paid: "green",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Waiting for Fund"), () => {
			listview.filter_area
				.clear()
				.then(() =>
					listview.filter_area.add([
						["Sick Leave Case", "status", "in", ["Employer Paid", "Fund Received"]],
					])
				);
		});
		listview.page.add_inner_button(__("Not Closed"), () => {
			listview.filter_area
				.clear()
				.then(() => listview.filter_area.add([["Sick Leave Case", "closed", "=", 0]]));
		});
		listview.page.add_inner_button(__("Find Unregistered Sick Days"), () => {
			frappe.prompt(
				[
					{
						fieldname: "company",
						fieldtype: "Link",
						options: "Company",
						label: __("Company"),
						default: frappe.defaults.get_user_default("Company"),
						reqd: 1,
					},
				],
				(values) =>
					frappe
						.call({
							method: "erpnext.payroll_ua.doctype.sick_leave_case.sick_leave_case.find_unregistered",
							args: values,
							freeze: true,
						})
						.then(({ message }) => {
							frappe.show_alert({
								message: __("Created {0} draft cases — enter the certificate numbers.", [
									(message || []).length,
								]),
								indicator: "green",
							});
							listview.refresh();
						}),
				__("Find Unregistered Sick Days"),
				__("Find")
			);
		});
	},
};
