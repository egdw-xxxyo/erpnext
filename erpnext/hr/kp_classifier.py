import csv
import os
from functools import cache

import frappe
from frappe import _

SOURCE = os.path.join(os.path.dirname(__file__), "kp_professions.csv")
SEARCH_LIMIT = 50


@cache
def professions():
	with open(SOURCE, encoding="utf-8", newline="") as f:
		return tuple((row["kp_code"], row["job_title"]) for row in csv.DictReader(f))


def matches(term):
	words = term.lower().split()
	return lambda profession: all(word in f"{profession[0]} {profession[1]}".lower() for word in words)


def as_option(profession):
	kp_code, job_title = profession
	return {"value": f"{kp_code} {job_title}", "label": kp_code, "description": job_title}


@frappe.whitelist()
def search_kp_professions(txt=""):
	found = filter(matches(txt or ""), professions())
	return [as_option(profession) for _i, profession in zip(range(SEARCH_LIMIT), found, strict=False)]


def split_selected_profession(value):
	kp_code, _sep, job_title = (value or "").partition(" ")
	return kp_code, job_title


def validate_kp_profession(doc, method=None):
	if doc.kp_code and " " in doc.kp_code:
		doc.kp_code, doc.kp_job_title = split_selected_profession(doc.kp_code)

	if not doc.kp_code:
		doc.kp_job_title = None
		return

	if not doc.has_value_changed("kp_code") and not doc.has_value_changed("kp_job_title"):
		return

	if (doc.kp_code, doc.kp_job_title) not in professions():
		frappe.throw(
			_("KP Code {0} with professional title {1} is not in the Classifier of Professions").format(
				frappe.bold(doc.kp_code), frappe.bold(doc.kp_job_title or "")
			)
		)
