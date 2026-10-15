(() => {
	const settings = frappe.listview_settings["Purchase Invoice"];
	const onload = settings.onload;
	settings.onload = function (listview) {
		onload?.(listview);
		const column_html = listview.get_column_html.bind(listview);
		listview.get_column_html = function (col, doc, mobile) {
			const html = column_html(col, doc, mobile);
			if (col.df?.fieldname !== "grand_total") return html;
			const values = doc.__supplier_vat;
			return (
				["net", "vat"]
					.map((key) => {
						const amount = values?.payer
							? format_currency(values.totals[key], doc.currency)
							: "—";
						return `<div class="list-row-col text-right hidden-xs ellipsis supplier-vat-list-col" style="flex:0 0 110px">${amount}</div>`;
					})
					.join("") + html
			);
		};
		const header_html = listview.get_header_html.bind(listview);
		listview.get_header_html = function () {
			const header = $(header_html());
			const total = header.find('[data-fieldname="grand_total"]').first();
			for (const label of [__("Excluding VAT"), __("VAT")]) {
				total.before(
					$(
						'<div class="list-row-col text-right hidden-xs ellipsis supplier-vat-list-col" style="flex:0 0 110px"></div>'
					).text(label)
				);
			}
			return header.prop("outerHTML");
		};
		const render = listview.render.bind(listview);
		listview.render = function () {
			render();
			const token = (listview.__vat_request || 0) + 1;
			listview.__vat_request = token;
			if (!listview.data.length) return;
			const requests = [];
			for (let offset = 0; offset < listview.data.length; offset += 500) {
				requests.push(
					frappe.call({
						method: "erpnext.accounts.supplier_vat_display.get_invoice_list_vat",
						args: { names: listview.data.slice(offset, offset + 500).map((doc) => doc.name) },
					})
				);
			}
			Promise.all(requests).then((responses) => {
				if (token !== listview.__vat_request) return;
				const values = Object.assign({}, ...responses.map((response) => response.message || {}));
				for (const doc of listview.data) doc.__supplier_vat = values[doc.name];
				render();
			});
		};
	};
})();
