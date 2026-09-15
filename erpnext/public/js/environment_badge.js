const ENV_BADGES = {
	prod: { label: "Prod", color: "#e03131" },
	test: { label: "Test", color: "#2f9e44" },
	local: { label: "Local", color: "#1c7ed6" },
};

function get_environment_badge() {
	return ENV_BADGES[frappe.boot && frappe.boot.instance_env];
}

function add_environment_badge() {
	const env = get_environment_badge();
	document.querySelectorAll(".sidebar-header .header-subtitle").forEach((subtitle) => {
		if (subtitle.querySelector(".env-badge")) return;
		const badge = document.createElement("span");
		badge.className = "env-badge";
		badge.textContent = __(env.label, null, "Environment badge");
		badge.style.cssText = `background:${env.color};color:#fff;font-size:10px;font-weight:600;line-height:1;padding:2px 5px;border-radius:4px;margin-left:6px;vertical-align:middle;text-transform:uppercase;`;
		subtitle.appendChild(badge);
	});
}

$(document).ready(() => {
	if (!get_environment_badge()) return;
	add_environment_badge();
	new MutationObserver(add_environment_badge).observe(document.body, { childList: true, subtree: true });
});
