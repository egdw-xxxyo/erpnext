# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _

ENGAGEMENT_CHANNELS = {
	"Онлайн": ("Сайт", "Соціальні мережі", "Месенджери (онлайн)"),
	"Офлайн": ("Виставка", "Конференція", "Форум", "Презентація"),
	"Рекомендації": ("Клієнт", "Партнер", "Особисте знайомство"),
	"Холодний контакт": ("Продзвони баз", "LinkedIn", "Email", "Месенджери (холодний контакт)"),
	"Державні закупівлі": ("Прозоро", "АОЗ", "ДРСЗІ", "DOTChain / Brave1", "Закриті закупівлі"),
	"Партнерські організації": ("Дилери", "Дистриб'ютори", "Виробники", "Інтегратори"),
	"Інше": (),
}


def validate(doc, method=None):
	validate_channel_detail(doc)


def validate_channel_detail(doc):
	if not doc.get("utm_medium"):
		return

	channel = frappe.db.get_value("UTM Medium", doc.utm_medium, "engagement_channel")
	if channel and channel != doc.get("utm_source"):
		frappe.throw(
			_("{0} belongs to the engagement channel {1}").format(
				frappe.bold(doc.utm_medium), frappe.bold(channel)
			),
			title=_("Invalid Engagement Channel Detail"),
		)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def engagement_channel_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | None
):
	return _search_in_order(tuple(ENGAGEMENT_CHANNELS), txt, start, page_len)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def engagement_channel_detail_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict | None
):
	channel = (filters or {}).get("engagement_channel")
	details = (
		ENGAGEMENT_CHANNELS.get(channel, ())
		if channel
		else tuple(detail for channel_details in ENGAGEMENT_CHANNELS.values() for detail in channel_details)
	)
	return _search_in_order(details, txt, start, page_len)


def _search_in_order(values, txt, start, page_len):
	needle = (txt or "").casefold()
	return [(value,) for value in values if needle in value.casefold()][start : start + page_len]
