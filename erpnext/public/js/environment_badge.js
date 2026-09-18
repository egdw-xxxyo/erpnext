const ENV_BANNERS = {
	test: { label: "Test server", icon: "fa-flask", color: "#6741d9", background: "#f0ebfb" },
	local: { label: "Local server", icon: "fa-laptop", color: "#1864ab", background: "#e7f1fb" },
};

function get_environment_banner() {
	return ENV_BANNERS[frappe.boot && frappe.boot.instance_env];
}

function add_environment_style(env) {
	if (document.getElementById("env-banner-style")) return;
	const style = document.createElement("style");
	style.id = "env-banner-style";
	style.textContent = `
		.body-sidebar .env-banner {
			margin: -8px -8px 0;
			min-height: 36px;
			display: flex;
			align-items: center;
			justify-content: center;
			flex: 0 0 auto;
			background: ${env.background};
			color: ${env.color};
			font-size: var(--text-sm);
			border-bottom: 1px solid var(--sidebar-border-color);
			white-space: nowrap;
			overflow: hidden;
		}
		.body-sidebar .env-banner .env-banner-label { display: none; }
		.body-sidebar-container.expanded .env-banner .env-banner-label { display: inline; }
		.body-sidebar-container.expanded .env-banner .env-banner-icon { display: none; }
		[data-theme="dark"] .body-sidebar .env-banner { background: ${env.color}; color: #fff; }
	`;
	document.head.appendChild(style);
}

function add_environment_banner() {
	const env = get_environment_banner();
	document.querySelectorAll(".body-sidebar").forEach((sidebar) => {
		if (sidebar.querySelector(".env-banner")) return;
		const label = __(env.label, null, "Environment banner");
		const banner = document.createElement("div");
		banner.className = "env-banner";
		banner.title = label;
		banner.innerHTML = `<i class="fa ${env.icon} env-banner-icon"></i><span class="env-banner-label"></span>`;
		banner.querySelector(".env-banner-label").textContent = label;
		sidebar.prepend(banner);
	});
}

$(document).ready(() => {
	const env = get_environment_banner();
	if (!env) return;
	add_environment_style(env);
	add_environment_banner();
	new MutationObserver(add_environment_banner).observe(document.body, { childList: true, subtree: true });
});
