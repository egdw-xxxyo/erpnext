// Setup QR next to the login form's email field.
//
// The mobile app (erpnext-mobile-kalheon) needs three things before it can log in: this
// site's URL, a label for it (Prod/Dev/...) and the user's login. Typing a LAN URL on a
// phone keyboard is the slow part, so the desk login page offers them as a QR the app
// scans with the button next to its own login field.
//
// Nothing here is authenticated — the page is the login page — and the payload holds no
// secret: URL, instance label, and whatever login is typed in the form. The password is
// always typed on the phone.

const ENDPOINT = "/api/method/erpnext.devices.mobile_app_api.get_provisioning_qr";

function build_button() {
	const button = document.createElement("button");
	button.type = "button";
	button.className = "btn btn-default btn-sm mobile-qr-btn";
	button.title = "QR для мобільного застосунку";
	button.setAttribute("aria-label", "QR для мобільного застосунку");
	button.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
		<path d="M1 1h6v6H1V1zm1.5 1.5v3h3v-3h-3zM9 1h6v6H9V1zm1.5 1.5v3h3v-3h-3zM1 9h6v6H1V9zm1.5 1.5v3h3v-3h-3zM9 9h2v2H9V9zm4 0h2v2h-2V9zm-4 4h2v2H9v-2zm4 0h2v2h-2v-2z"/>
	</svg>`;
	return button;
}

function escape_html(text) {
	const div = document.createElement("div");
	div.textContent = text || "";
	return div.innerHTML;
}

function render_dialog(data) {
	const existing = document.querySelector(".mobile-qr-overlay");
	if (existing) existing.remove();

	const overlay = document.createElement("div");
	overlay.className = "mobile-qr-overlay";
	overlay.innerHTML = `
		<div class="mobile-qr-card">
			<div class="mobile-qr-title">${escape_html(data.instance_name)}</div>
			<img class="mobile-qr-image" alt="QR" src="${data.qr_data_uri}">
			<div class="mobile-qr-hint">Скануйте кнопкою QR на екрані входу застосунку</div>
			<button type="button" class="btn btn-default btn-sm mobile-qr-close">Закрити</button>
		</div>`;
	const close = () => overlay.remove();
	overlay.addEventListener("click", (e) => {
		if (e.target === overlay || e.target.classList.contains("mobile-qr-close")) close();
	});
	document.addEventListener("keydown", function esc(e) {
		if (e.key === "Escape") {
			close();
			document.removeEventListener("keydown", esc);
		}
	});
	document.body.appendChild(overlay);
}

async function show_qr(login) {
	const url = `${ENDPOINT}?login=${encodeURIComponent(login || "")}`;
	const response = await fetch(url, { headers: { Accept: "application/json" } });
	if (!response.ok) throw new Error(`HTTP ${response.status}`);
	const body = await response.json();
	render_dialog(body.message || {});
}

function mount() {
	const input = document.getElementById("login_email");
	if (!input || document.querySelector(".mobile-qr-btn")) return;

	const button = build_button();
	button.addEventListener("click", async () => {
		button.disabled = true;
		try {
			await show_qr(input.value);
		} catch (e) {
			console.error("mobile setup QR failed", e);
		} finally {
			button.disabled = false;
		}
	});

	// The field sits in a .form-group; the button goes beside its label so it never
	// disturbs the input's own layout (and keeps working when the page re-renders it).
	const group = input.closest(".form-group") || input.parentElement;
	const label = group.querySelector("label");
	if (label) {
		label.classList.add("mobile-qr-label");
		label.appendChild(button);
	} else {
		group.appendChild(button);
	}
}

// The login page swaps between its sign-in/forgot-password/signup sections without a
// reload, so re-attach whenever the section changes rather than only on first paint.
function watch() {
	mount();
	const container = document.querySelector(".page-card-body") || document.body;
	new MutationObserver(() => mount()).observe(container, { childList: true, subtree: true });
}

if (window.location.pathname === "/login") {
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", watch);
	} else {
		watch();
	}
}
