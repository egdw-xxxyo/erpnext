# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Every enumeration of the technical documentation register, in one place.

The stored values are Ukrainian because that is what the register shows and, more to the
point, what the rows already carried when the doctypes were codified out of dev — the
Select values here are the ones those rows hold, so nothing needs a data patch. That
makes any comparison in code language-dependent, so nothing in the module compares
against a literal: it imports from here, and a future rename stays a data patch plus one
edit of this file.

Every value here is one the register actually produces. Seats kept for a routing engine
that was never built — an approval status nothing sets, an audit event nothing writes —
were removed: an enumeration is read as a promise of what can happen, and a value no code
can ever store is a promise the module does not keep.
"""

MODULE_NAME = "Technical Documentation"

ROLE_VIEWER = "Technical Documentation Viewer"
ROLE_EDITOR = "Technical Documentation Editor"
ROLE_MANAGER = "Technical Documentation Manager"

DOCUMENT_DRAFT = "Чернетка"
DOCUMENT_EFFECTIVE = "Чинний"
DOCUMENT_SUPERSEDED = "Замінений"
DOCUMENT_CANCELLED = "Скасований"
DOCUMENT_ARCHIVED = "Архівний"

DOCUMENT_STATUSES = (
	DOCUMENT_DRAFT,
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

RELATION_SUPERSEDES = "Замінює"
RELATION_SUPERSEDED_BY = "Замінений документом"
RELATION_INCLUDES = "Включає до комплекту"
RELATION_INCLUDED_IN = "Входить до комплекту"
RELATION_RELATED_TO = "Повʼязаний з"
RELATION_BASIS_FOR = "Є підставою для"
RELATION_BASED_ON = "Розроблений на підставі"
RELATION_CANCELS = "Скасовує"
RELATION_PREVIOUS_EDITION = "Попередня редакція"
RELATION_NEXT_EDITION = "Наступна редакція"

RELATION_TYPES = (
	RELATION_SUPERSEDES,
	RELATION_SUPERSEDED_BY,
	RELATION_INCLUDES,
	RELATION_INCLUDED_IN,
	RELATION_RELATED_TO,
	RELATION_BASIS_FOR,
	RELATION_BASED_ON,
	RELATION_CANCELS,
	RELATION_PREVIOUS_EDITION,
	RELATION_NEXT_EDITION,
)

# A relation is read as a sentence — the main document, the type, the related document — so
# a type that only reads one way can only be recorded from one card. «Замінює» has had its
# mirror «Замінений документом» from the start; «Включає до комплекту» and «Є підставою для»
# are the mirrors the vocabulary was missing, and without them a specification could not say
# what belongs to it without stating the opposite of what was meant.
#
# The package pair is named after the package rather than after annexes: completeness is
# counted off these two types and no other, and «Має додаток» read as one relation among
# ten, where nothing said that picking it — and only it — is what fills a required row.

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
AUDIT_OTHER = "Інше"

AUDIT_EVENTS = (
	AUDIT_CREATED,
	AUDIT_NEW_REVISION,
	AUDIT_MADE_EFFECTIVE,
	AUDIT_STATUS_CHANGED,
	AUDIT_RESPONSIBLE_CHANGED,
	AUDIT_ARCHIVED,
	AUDIT_CANCELLED,
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
ATTRIBUTE_DOCTYPE = "Product Attribute"
