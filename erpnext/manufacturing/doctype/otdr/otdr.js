function copy_row(label, value, hint) {
	const safe = frappe.utils.escape_html(value || "");
	return `
		<div style="margin-bottom: 14px;">
			<div style="font-weight: 600; margin-bottom: 4px;">${label}</div>
			<div style="display: flex; gap: 8px; align-items: stretch;">
				<input type="text" readonly value="${safe}"
					style="flex: 1; font-family: monospace; font-size: 13px;
						padding: 6px 10px; border: 1px solid var(--border-color);
						border-radius: 4px; background: var(--bg-light-gray, #f5f5f5);" />
				<button class="btn btn-default btn-sm otdr-copy-btn" data-value="${safe}">
					${__("Скопіювати")}
				</button>
			</div>
			${hint ? `<div class="text-muted" style="font-size: 11px; margin-top: 4px;">${hint}</div>` : ""}
		</div>
	`;
}

function render_sync_credentials(frm) {
	const base_url = window.location.origin;
	frm.fields_dict.endpoints_html.$wrapper.html(`
		<div style="max-width: 720px;">
			${copy_row(__("URL сервера"), base_url, __("Поле Server URL в otdr-sync."))}
			<div class="text-muted" style="font-size: 12px;">
				${__("Натисніть \"Підключити рефлектометр\", щоб згенерувати api_key/api_secret для поточного користувача та отримати QR-код.")}
			</div>
		</div>
	`);

	frm.fields_dict.endpoints_html.$wrapper.find(".otdr-copy-btn").on("click", function () {
		const val = $(this).attr("data-value");
		navigator.clipboard.writeText(val).then(() => {
			frappe.show_alert({ message: __("Скопійовано"), indicator: "green" });
		});
	});
}

function render_live_status(frm) {
	const wrap = frm.fields_dict.live_status_html?.$wrapper;
	if (!wrap) return;
	const s = frm._otdr_live || {};
	const last_seen = s.last_seen;
	const hb = Number(s.heartbeat_interval_s) || 10;
	const threshold = Math.max(20, hb * 2);
	const base = Number.isFinite(Number(s.age_s)) ? Number(s.age_s) : null;
	const received = frm._otdr_received_at || Date.now();
	const age = last_seen && base !== null ? base + Math.floor((Date.now() - received) / 1000) : null;
	const app_online = age !== null && age < threshold;
	const ble_ready = app_online && String(s.ble_ready || "") === "1";

	const pill = (ok, label_on, label_off, sub) => {
		const color = ok ? "#1e8e3e" : "#d93025";
		const bg = ok ? "rgba(30,142,62,0.12)" : "rgba(217,48,37,0.12)";
		const text = ok ? label_on : label_off;
		const sub_html = sub ? ` <span style="opacity:.7; font-weight:400;">${sub}</span>` : "";
		return `<span style="display:inline-block; padding:4px 10px; border-radius:4px;
			background:${bg}; color:${color}; font-weight:600; margin-right:8px;">● ${text}${sub_html}</span>`;
	};

	const app_sub = age !== null ? __("{0} с тому", [age]) : __("ніколи");
	const ble_sub = ble_ready ? "" : (app_online ? __("не підключено") : "");
	const badge_html = !last_seen
		? `<span style="display:inline-block; padding:4px 10px; border-radius:4px;
			background: var(--bg-gray, #eee); color: var(--text-muted);">● ${__("Не підключався")}</span>`
		: pill(app_online, __("Застосунок підключено"), __("Застосунок недоступний"), app_sub)
		  + pill(ble_ready, __("Пристрій BLE готовий"), __("Пристрій BLE недоступний"), ble_sub);

	const app_version = s.app_version;
	const min_version = s.min_app_version;
	const app_client = s.app_client;
	const app_incompatible = app_version && String(s.app_compatible || "") === "0";
	const version_warn = app_incompatible ? `
		<div style="margin-top: 12px; padding: 8px 10px; border-left: 3px solid #f0ad4e;
			background: #fff8e5; color: #8a6d3b; font-size: 12px; max-width: 480px;">
			${__("Версія застосунку ({0}) застаріла. Оновіть до {1} або новішої — логіку рефлектометра змінено.", [app_version, min_version])}
		</div>` : "";

	const row = (label, value) => value ? `
		<tr>
			<td style="padding: 4px 12px 4px 0; color: var(--text-muted);">${label}</td>
			<td style="padding: 4px 0; font-family: monospace;">${frappe.utils.escape_html(String(value))}</td>
		</tr>` : "";

	const progress = s.progress, total = s.total;
	const pct = (progress && total && Number(total) > 0)
		? Math.round((Number(progress) * 100) / Number(total))
		: null;
	const bar_html = pct !== null ? `
		<div style="margin-top: 8px; max-width: 480px;">
			<div style="height: 8px; background: var(--bg-gray, #eee); border-radius: 4px; overflow: hidden;">
				<div style="height: 100%; width: ${pct}%; background: #1e8e3e;"></div>
			</div>
			<div class="text-muted" style="font-size: 11px; margin-top: 4px;">
				${progress} / ${total} (${pct}%)
			</div>
		</div>` : "";

	wrap.html(`
		<div style="padding: 4px 0;">
			<div style="margin-bottom: 12px;">${badge_html}</div>
			<table style="border-collapse: collapse;">
				${row(__("Стан"), s.status)}
				${row(__("Файл"), s.file)}
				${row(__("Останнє звернення"), s.last_seen)}
				${row(__("Клієнт"), app_client)}
				${row(__("Версія застосунку"), app_version)}
				${row(__("Мін. сумісна версія"), min_version)}
			</table>
			${bar_html}
			${version_warn}
		</div>
	`);
}

function open_connect_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Підключити рефлектометр"),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "body" },
		],
	});
	const $body = d.fields_dict.body.$wrapper;

	function render_body(default_url, source) {
		const is_local = /^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|$)/i.test(default_url);
		const warn_local = is_local
			? `<div style="margin-top: 8px; padding: 8px 10px; border-left: 3px solid #f0ad4e; background: #fff8e5; color: #8a6d3b; font-size: 12px;">
				${__("URL містить localhost — телефон/інший ПК не зможе підключитись. Заповніть \"Публічний URL сервера\" в OTDR Configuration або введіть LAN IP тут вручну (напр. http://192.168.1.10:8080).")}
			</div>` : "";
		const source_hint = source === "configuration"
			? `<div class="text-muted" style="font-size: 11px; margin-top: 4px;">${__("Взято з OTDR Configuration → Публічний URL сервера.")}</div>`
			: "";

		$body.html(initial(default_url, warn_local + source_hint));
		bind_gen_click();
	}

	const initial = (default_url, extra_html) => `
		<div style="max-width: 640px;">
			<div style="margin-bottom: 12px;">
				<label style="font-weight: 600; display: block; margin-bottom: 4px;">${__("URL сервера")}</label>
				<input type="text" id="otdr-server-url" value="${frappe.utils.escape_html(default_url)}"
					style="width: 100%; font-family: monospace; padding: 6px 10px; border: 1px solid var(--border-color); border-radius: 4px;" />
				${extra_html || ""}
			</div>
			<div style="margin-top: 20px; padding: 12px; border: 1px solid #f5c6cb; background: #f8d7da; color: #721c24; border-radius: 4px;">
				<b>${__("Увага")}:</b>
				${__("API-ключ і секрет буде показано лише один раз. Скопіюйте їх або відскануйте QR перед закриттям вікна. Попередні ключі цього користувача будуть недійсними.")}
			</div>
			<div style="margin-top: 16px;">
				<button class="btn btn-primary" id="otdr-gen-keys-btn">
					${__("Згенерувати ключі")}
				</button>
			</div>
			<div id="otdr-bundle-result" style="margin-top: 16px;"></div>
		</div>
	`;

	function bind_gen_click() {
		$body.find("#otdr-gen-keys-btn").on("click", function () {
			const $btn = $(this);
			const url_val = ($body.find("#otdr-server-url").val() || "").trim().replace(/\/+$/, "");
			if (!url_val) { frappe.show_alert({ message: __("Введіть URL"), indicator: "orange" }); return; }
			$btn.prop("disabled", true).text(__("Генерація..."));
			frappe.call({
				method: "erpnext.manufacturing.doctype.otdr.otdr_api.generate_connect_bundle",
				args: { otdr_name: frm.doc.name, server_url: url_val },
				callback: (r) => {
					$btn.prop("disabled", false).text(__("Згенерувати ще раз"));
					if (!r.message) return;
					render_bundle($body.find("#otdr-bundle-result"), r.message);
				},
				error: () => {
					$btn.prop("disabled", false).text(__("Згенерувати ключі"));
				},
			});
		});
	}

	$body.html(`<div class="text-muted" style="padding: 12px;">${__("Завантаження...")}</div>`);
	frappe.call({
		method: "erpnext.manufacturing.doctype.otdr.otdr_api.get_default_connect_url",
		args: { otdr_name: frm.doc.name },
		callback: (r) => {
			const url = r.message?.server_url || window.location.origin;
			render_body(url, r.message?.source || "");
		},
		error: () => { render_body(window.location.origin, ""); },
	});

	d.$wrapper.on("click", ".otdr-copy-btn", function () {
		const val = $(this).attr("data-value");
		navigator.clipboard.writeText(val).then(() => {
			frappe.show_alert({ message: __("Скопійовано"), indicator: "green" });
		});
	});

	d.show();
}

function render_bundle($container, m) {
	const qr = frappe.utils.escape_html(m.qr_data_uri);
	$container.html(`
		<hr />
		${copy_row(__("API Key"), m.api_key)}
		${copy_row(__("API Secret"), m.api_secret, __("Показано один раз. Збережіть у безпечному місці."))}
		${copy_row(__("Конфіг (base64)"), m.token, __("Вставте в otdr-sync (одразу заповнить URL, ключ, секрет)."))}
		<div style="margin-top: 16px;">
			<div style="font-weight: 600; margin-bottom: 4px;">${__("QR-код")}</div>
			<div style="background: white; display: inline-block; padding: 8px; border: 1px solid var(--border-color); border-radius: 4px;">
				<img src="${qr}" style="display: block; max-width: 320px;" />
			</div>
			<div class="text-muted" style="font-size: 11px; margin-top: 4px;">
				${__("Відскануйте в мобільному застосунку для швидкого налаштування.")}
			</div>
		</div>
	`);
}

frappe.ui.form.on("OTDR", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.fields_dict.endpoints_html.$wrapper.html(
				`<div class="text-muted" style="padding: 12px;">${__("Збережіть документ, щоб отримати API ключ.")}</div>`
			);
			return;
		}
		render_sync_credentials(frm);

		frm.add_custom_button(__("Підключити рефлектометр"), () => open_connect_dialog(frm))
			.addClass("btn-primary");

		const listening = !!frm.doc.sync_listening;
		frm.toggle_display("btn_start_sync", !listening);
		frm.toggle_display("btn_stop_sync", listening);

		frm._otdr_live = frm._otdr_live || {};
		render_live_status(frm);

		frappe.call({
			method: "erpnext.manufacturing.doctype.otdr.otdr.get_status",
			args: { otdr_name: frm.doc.name },
			callback: (r) => {
				if (r.message) {
					frm._otdr_live = r.message;
					frm._otdr_received_at = Date.now();
					render_live_status(frm);
				}
			},
		});

		if (frm._otdr_realtime_subscribed !== frm.doc.name) {
			const rt = frappe.realtime || {};
			const sock = rt.socket;
			console.log("[OTDR] realtime diag", {
				has_realtime: !!rt,
				has_socket: !!sock,
				connected: sock && sock.connected,
				id: sock && sock.id,
				nsp: sock && sock.nsp,
				disable_async: frappe.boot && frappe.boot.disable_async,
				sitename: frappe.boot && frappe.boot.sitename,
			});
			if (sock) {
				sock.on("connect", () => console.log("[OTDR] socket connect event id=", sock.id));
				sock.on("connect_error", (e) => console.log("[OTDR] socket connect_error:", e && e.message));
				sock.on("disconnect", (r) => console.log("[OTDR] socket disconnect:", r));
				sock.onAny && sock.onAny((event, ...args) => {
					if (event === "otdr_status_update") console.log("[OTDR] onAny otdr_status_update", args);
				});
			}
			if (frappe.realtime.doc_subscribe) {
				frappe.realtime.doc_subscribe("OTDR", frm.doc.name);
				console.log("[OTDR] doc_subscribe sent");
			} else {
				frappe.realtime.doctype_subscribe("OTDR");
				console.log("[OTDR] doctype_subscribe sent (fallback)");
			}
			frappe.realtime.off("otdr_status_update");
			frappe.realtime.on("otdr_status_update", (data) => {
				console.log("[OTDR] realtime event received:", data);
				if (!data || !cur_frm || cur_frm.doc.name !== frm.doc.name) {
					console.log("[OTDR] skipped — wrong form context");
					return;
				}
				if (data.otdr && data.otdr !== frm.doc.name) {
					console.log("[OTDR] skipped — name mismatch", data.otdr, "vs", frm.doc.name);
					return;
				}
				frm._otdr_live = data;
				frm._otdr_received_at = Date.now();
				render_live_status(frm);
			});
			frm._otdr_realtime_subscribed = frm.doc.name;
			console.log("[OTDR] listener attached for otdr_status_update");
		}

		if (frm._otdr_status_timer) clearInterval(frm._otdr_status_timer);
		frm._otdr_status_timer = setInterval(() => {
			if (!cur_frm || cur_frm.doc.name !== frm.doc.name) {
				clearInterval(frm._otdr_status_timer);
				frm._otdr_status_timer = null;
				return;
			}
			render_live_status(frm);
		}, 1000);
	},

	onload_post_render(frm) {
		// nothing — timer set up in refresh
	},

	btn_start_sync(frm) {
		if (frm.is_new()) {
			frappe.msgprint(__("Спочатку збережіть документ."));
			return;
		}
		frappe.call({
			method: "erpnext.manufacturing.doctype.otdr.otdr.set_sync_listening",
			args: { otdr_name: frm.doc.name, listening: 1 },
			callback: () => {
				frappe.show_alert({ message: __("Слухання увімкнено"), indicator: "green" });
				frm.reload_doc();
			},
		});
	},

	btn_stop_sync(frm) {
		if (frm.is_new()) return;
		frappe.call({
			method: "erpnext.manufacturing.doctype.otdr.otdr.set_sync_listening",
			args: { otdr_name: frm.doc.name, listening: 0 },
			callback: () => {
				frappe.show_alert({ message: __("Слухання вимкнено"), indicator: "orange" });
				frm.reload_doc();
			},
		});
	},

});
