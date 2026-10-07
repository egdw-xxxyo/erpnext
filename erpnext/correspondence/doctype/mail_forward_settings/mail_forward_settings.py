import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from erpnext.correspondence.forwarding_accounts import MANAGER_ROLE, SENDER, WATCHED, apply_defaults
from erpnext.correspondence.imap_folders import (
	MANUAL,
	decode_modified_utf7,
	folder_key,
	parse_list_response,
	select_folders,
)
from erpnext.correspondence.imap_uids import FolderState, parse_status

FOLDER_FIELDS = ("folder_name", "append_to", "uidvalidity", "uidnext")
ERROR_LIMIT = 2000
SYNC_JOB = "erpnext.correspondence.doctype.mail_forward_settings.mail_forward_settings.sync_new_mailboxes"


class MailForwardSettings(Document):
	def validate(self):
		self.validate_mailboxes()
		self.validate_sender_account()

	def on_update(self):
		for row in self.mailboxes:
			apply_defaults(row.email_account, WATCHED)
		if self.sender_account:
			apply_defaults(self.sender_account, SENDER)
		if any(not row.last_folder_sync for row in self.mailboxes):
			frappe.enqueue(SYNC_JOB, job_id=SYNC_JOB, deduplicate=True, enqueue_after_commit=True)

	def validate_mailboxes(self):
		accounts = [row.email_account for row in self.mailboxes]
		duplicates = sorted({account for account in accounts if accounts.count(account) > 1})
		if duplicates:
			frappe.throw(_("Mailbox {0} is listed more than once").format(", ".join(duplicates)))
		for row in self.mailboxes:
			validate_watched_account(row.email_account)
			row.forward_since = row.forward_since or now_datetime()

	def validate_sender_account(self):
		if not self.sender_account:
			if self.enabled:
				frappe.throw(_("Choose the account the copies are sent from before enabling forwarding"))
			return
		sender_address = account_address(self.sender_account)
		if sender_address in {account_address(row.email_account) for row in self.mailboxes}:
			frappe.throw(
				_(
					"Copies cannot be sent from {0}: it is the address of a watched mailbox, and the copies would appear in its Sent folder"
				).format(sender_address)
			)
		if not frappe.db.get_value("Email Account", self.sender_account, "enable_outgoing"):
			frappe.throw(_("Email Account {0} has no outgoing mail enabled").format(self.sender_account))


def account_address(name: str | None) -> str:
	return (frappe.db.get_value("Email Account", name, "email_id") or "").strip().lower()


def validate_watched_account(name: str):
	account = frappe.db.get_value("Email Account", name, ["enable_incoming", "use_imap"], as_dict=True)
	if not (account and account.enable_incoming and account.use_imap):
		frappe.throw(_("Email Account {0} must receive mail over IMAP").format(name))


def open_server(account):
	server = account.get_incoming_server(in_receive=True, email_sync_rule="ALL")
	if not server or not getattr(server, "imap", None):
		frappe.throw(_("Could not connect to {0}").format(account.email_id))
	return server


def fetch_folders(account) -> list:
	server = open_server(account)
	try:
		status, entries = server.imap.list()
	finally:
		server.logout()
	if status != "OK":
		frappe.throw(_("The server refused to list folders of {0}").format(account.email_id))
	return parse_list_response(entries)


def folder_state(server, name: str) -> FolderState | None:
	status, data = server.imap.status(f'"{name}"', "(UIDVALIDITY UIDNEXT)")
	return parse_status(data[0]) if status == "OK" and data and data[0] else None


def fetch_states(account, names: list[str]) -> dict[str, FolderState]:
	if not names:
		return {}
	server = open_server(account)
	try:
		states = {name: folder_state(server, name) for name in names}
	finally:
		server.logout()
	return {name: state for name, state in states.items() if state and state.uidnext}


def with_starting_point(row: dict, state: FolderState | None) -> dict:
	return {**row, "uidvalidity": state.uidvalidity, "uidnext": str(state.uidnext)} if state else row


def apply_folders(account, wanted: list[str]) -> bool:
	current = [{field: row.get(field) for field in FOLDER_FIELDS} for row in account.imap_folder]
	existing = {folder_key(row["folder_name"]): row for row in current}
	kept = [existing.get(folder_key(name), {"folder_name": name}) for name in wanted]
	states = fetch_states(account, [row["folder_name"] for row in kept if not row.get("uidvalidity")])
	rows = [with_starting_point(row, states.get(row["folder_name"])) for row in kept]
	if rows == current:
		return False
	account.set("imap_folder", rows)
	account.flags.ignore_validate = True
	account.save(ignore_permissions=True)
	return True


def sync_mailbox(row) -> bool:
	account = frappe.get_doc("Email Account", row.email_account)
	wanted = (
		[folder.folder_name for folder in account.imap_folder]
		if row.folder_mode == MANUAL
		else select_folders(fetch_folders(account), row.folder_mode)
	)
	if not wanted:
		frappe.throw(_("No folders to read were found in {0}").format(account.email_id))
	return apply_folders(account, wanted)


def record_sync(row, error: str | None):
	frappe.db.set_value(
		"Mail Forward Mailbox",
		row.name,
		{"last_folder_sync": now_datetime(), "folder_sync_error": (error or "")[-ERROR_LIMIT:] or None},
		update_modified=False,
	)


def sync_row(row) -> str | None:
	savepoint = f"mail_forward_folders_{row.idx}"
	frappe.db.savepoint(savepoint)
	try:
		sync_mailbox(row)
		record_sync(row, None)
		return None
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		error = frappe.get_traceback()
		record_sync(row, error)
		return error


def sync_all_mailboxes() -> dict[str, str | None]:
	settings = frappe.get_single("Mail Forward Settings")
	return {row.email_account: sync_row(row) for row in settings.mailboxes}


def sync_new_mailboxes() -> dict[str, str | None]:
	settings = frappe.get_single("Mail Forward Settings")
	return {row.email_account: sync_row(row) for row in settings.mailboxes if not row.last_folder_sync}


@frappe.whitelist()
def sync_folders_now():
	frappe.only_for(["System Manager", MANAGER_ROLE])
	results = sync_all_mailboxes()
	return [
		{
			"email_account": account,
			"error": bool(error),
			"folders": [
				decode_modified_utf7(name)
				for name in frappe.get_all(
					"IMAP Folder",
					filters={"parent": account, "parenttype": "Email Account"},
					pluck="folder_name",
					order_by="idx asc",
				)
			],
		}
		for account, error in results.items()
	]
