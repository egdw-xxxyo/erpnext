import frappe


def add_instance_env(bootinfo):
	bootinfo["instance_env"] = frappe.conf.get("instance_env")
