# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Every enumeration of the technical documentation register, in one place.

The stored values are Ukrainian because that is what the register shows and, more to the
point, what the rows already carried when the doctypes were codified out of dev — the
Select values here are the ones those rows hold, so nothing needs a data patch. That
makes any comparison in code language-dependent, so nothing in the module compares
against a literal: it imports from here, and a future rename stays a data patch plus one
edit of this file.

Two document statuses (`На погодженні`, `Погоджено`) have no rows behind them yet. They
are seats kept for the approval wave, and adding a Select value never touches data.
"""

MODULE_NAME = "Technical Documentation"

ROLE_VIEWER = "Technical Documentation Viewer"
ROLE_EDITOR = "Technical Documentation Editor"
ROLE_MANAGER = "Technical Documentation Manager"

DOCUMENT_DRAFT = "Чернетка"
DOCUMENT_IN_APPROVAL = "На погодженні"
DOCUMENT_APPROVED = "Погоджено"
DOCUMENT_EFFECTIVE = "Чинний"
DOCUMENT_SUPERSEDED = "Замінений"
DOCUMENT_CANCELLED = "Скасований"
DOCUMENT_ARCHIVED = "Архівний"

DOCUMENT_STATUSES = (
	DOCUMENT_DRAFT,
	DOCUMENT_IN_APPROVAL,
	DOCUMENT_APPROVED,
	DOCUMENT_EFFECTIVE,
	DOCUMENT_SUPERSEDED,
	DOCUMENT_CANCELLED,
	DOCUMENT_ARCHIVED,
)

DOCUMENT_OUTDATED_STATUSES = (DOCUMENT_SUPERSEDED, DOCUMENT_CANCELLED, DOCUMENT_ARCHIVED)

REVISION_DRAFT = "Чернетка"
REVISION_APPROVED = "Затверджена"
REVISION_EFFECTIVE = "Чинна"
REVISION_SUPERSEDED = "Замінена"
REVISION_CANCELLED = "Скасована"

REVISION_STATUSES = (
	REVISION_DRAFT,
	REVISION_APPROVED,
	REVISION_EFFECTIVE,
	REVISION_SUPERSEDED,
	REVISION_CANCELLED,
)

MODIFICATION_DRAFT = "Чернетка"
MODIFICATION_EFFECTIVE = "Чинна"
MODIFICATION_SUPERSEDED = "Замінена"
MODIFICATION_CANCELLED = "Скасована"
MODIFICATION_ARCHIVED = "Архівна"

MODIFICATION_STATUSES = (
	MODIFICATION_DRAFT,
	MODIFICATION_EFFECTIVE,
	MODIFICATION_SUPERSEDED,
	MODIFICATION_CANCELLED,
	MODIFICATION_ARCHIVED,
)

CODIFICATION_NOT_STARTED = "Не розпочато"
CODIFICATION_PREPARING = "Підготовка документів"
CODIFICATION_TESTING = "На випробуваннях"
CODIFICATION_IN_PROGRESS = "На кодифікації"
CODIFICATION_DONE = "Кодифіковано"
CODIFICATION_REJECTED = "Відхилено"
CODIFICATION_CANCELLED = "Скасовано"

CODIFICATION_STATUSES = (
	CODIFICATION_NOT_STARTED,
	CODIFICATION_PREPARING,
	CODIFICATION_TESTING,
	CODIFICATION_IN_PROGRESS,
	CODIFICATION_DONE,
	CODIFICATION_REJECTED,
	CODIFICATION_CANCELLED,
)

CODIFICATION_OPEN_STATUSES = (
	CODIFICATION_PREPARING,
	CODIFICATION_TESTING,
	CODIFICATION_IN_PROGRESS,
)

RELATION_SUPERSEDES = "Замінює"
RELATION_SUPERSEDED_BY = "Замінений документом"
RELATION_ANNEX_TO = "Додаток до"
RELATION_RELATED_TO = "Повʼязаний з"
RELATION_BASED_ON = "Розроблений на підставі"
RELATION_CANCELS = "Скасовує"
RELATION_PREVIOUS_EDITION = "Попередня редакція"
RELATION_NEXT_EDITION = "Наступна редакція"

RELATION_TYPES = (
	RELATION_SUPERSEDES,
	RELATION_SUPERSEDED_BY,
	RELATION_ANNEX_TO,
	RELATION_RELATED_TO,
	RELATION_BASED_ON,
	RELATION_CANCELS,
	RELATION_PREVIOUS_EDITION,
	RELATION_NEXT_EDITION,
)

ATTACHMENT_SIGNATURE = "Підпис"
ATTACHMENT_MEDOC_RECEIPT = "Квитанція M.E.Doc"
ATTACHMENT_ANNEX = "Додаток"
ATTACHMENT_PROTOCOL = "Протокол"
ATTACHMENT_SCAN = "Скан"
ATTACHMENT_COVER_LETTER = "Супровідний лист"
ATTACHMENT_OTHER = "Інше"

ATTACHMENT_TYPES = (
	ATTACHMENT_SIGNATURE,
	ATTACHMENT_MEDOC_RECEIPT,
	ATTACHMENT_ANNEX,
	ATTACHMENT_PROTOCOL,
	ATTACHMENT_SCAN,
	ATTACHMENT_COVER_LETTER,
	ATTACHMENT_OTHER,
)

AUDIT_CREATED = "Створено"
AUDIT_NEW_REVISION = "Нова редакція"
AUDIT_MADE_EFFECTIVE = "Введено в дію"
AUDIT_STATUS_CHANGED = "Зміна статусу"
AUDIT_RESPONSIBLE_CHANGED = "Зміна відповідального"
AUDIT_ARCHIVED = "Архівовано"
AUDIT_CANCELLED = "Скасовано"
AUDIT_APPROVED = "Погоджено"
AUDIT_REJECTED = "Відхилено"
AUDIT_OTHER = "Інше"

AUDIT_EVENTS = (
	AUDIT_CREATED,
	AUDIT_NEW_REVISION,
	AUDIT_MADE_EFFECTIVE,
	AUDIT_STATUS_CHANGED,
	AUDIT_RESPONSIBLE_CHANGED,
	AUDIT_ARCHIVED,
	AUDIT_CANCELLED,
	AUDIT_APPROVED,
	AUDIT_REJECTED,
	AUDIT_OTHER,
)

COMPLETENESS_PRESENT = "Є"
COMPLETENESS_EXPIRED = "Прострочено"
COMPLETENESS_OUTDATED = "Не актуально"
COMPLETENESS_MISSING = "Немає"

DOCUMENT_DOCTYPE = "Technical Document"
REVISION_DOCTYPE = "Technical Document Revision"
RELATION_DOCTYPE = "Technical Document Relation"
SECTION_DOCTYPE = "Technical Document Section"
TYPE_DOCTYPE = "Technical Document Type"
AUDIT_DOCTYPE = "Technical Document Audit Entry"
MODIFICATION_DOCTYPE = "Product Modification"
CODIFICATION_DOCTYPE = "NATO Codification"

ALLOWED_LINK_DOCTYPES = (DOCUMENT_DOCTYPE,)
