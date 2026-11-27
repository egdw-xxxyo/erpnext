import frappe

from erpnext.technical_documentation.constants import (
	REVISION_APPROVED,
	REVISION_CANCELLED,
	REVISION_DOCTYPE,
	REVISION_DRAFT,
)


def execute():
	if not frappe.db.table_exists(REVISION_DOCTYPE):
		return

	revision = frappe.qb.DocType(REVISION_DOCTYPE)
	updates = (
		(revision.docstatus == 0, REVISION_DRAFT),
		((revision.docstatus == 1) & (revision.revision_status == REVISION_DRAFT), REVISION_APPROVED),
		(revision.docstatus == 2, REVISION_CANCELLED),
	)
	for condition, status in updates:
		(
			frappe.qb.update(revision)
			.set(revision.revision_status, status)
			.where(condition & (revision.revision_status != status))
			.run()
		)
