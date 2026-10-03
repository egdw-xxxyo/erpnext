from collections.abc import Iterator
from contextlib import suppress

import frappe
from frappe import _
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.email.receive import InboundMail
from frappe.utils import get_datetime, now_datetime

from erpnext.correspondence.forwarding_accounts import (
	SETTINGS,
	WATCHED,
	form_profile,
	forwarding_role,
	pending_changes,
)
from erpnext.correspondence.imap_uids import (
	FolderState,
	new_uids,
	parse_fetch,
	parse_status,
	progress_start,
	read_plan,
)


class ForwardingEmailAccount(EmailAccount):
	def onload(self):
		self.set_onload("mail_forwarding", form_profile(self.name))

	def validate(self):
		self.update(pending_changes(self, forwarding_role(self.name)))
		super().validate()

	def reads_folders_by_uid(self) -> bool:
		return bool(
			self.enable_incoming
			and self.use_imap
			and self.email_sync_option == "ALL"
			and self.service != "Frappe Mail"
			and forwarding_role(self.name) == WATCHED
		)

	def receive(self):
		if not self.reads_folders_by_uid():
			return super().receive()
		self.flags.folder_progress = {}
		try:
			return super().receive()
		finally:
			self.save_folder_progress()

	def get_inbound_mails(self) -> list[InboundMail]:
		if not self.reads_folders_by_uid():
			return super().get_inbound_mails()
		self.flags.folder_progress = self.flags.folder_progress or {}
		mails = []
		try:
			server = self.get_incoming_server(in_receive=True, email_sync_rule="ALL")
			self.flags.mail_check_started = now_datetime()
			try:
				for folder in self.imap_folder:
					for mail in self.read_folder(server, folder):
						mails.append(mail)
			finally:
				with suppress(Exception):
					server.imap.logout()
		except Exception:
			self.log_error(title=_("Error while connecting to email account {0}").format(self.name))
		return mails

	def read_folder(self, server, folder) -> Iterator[InboundMail]:
		quoted = f'"{folder.folder_name}"'
		status, data = server.imap.status(quoted, "(UIDVALIDITY UIDNEXT)")
		if status != "OK" or not data or not data[0]:
			return
		state = parse_status(data[0])
		plan = read_plan(folder.uidvalidity, folder.uidnext, state, self.reread_since())
		if not plan:
			return
		server.imap.select(quoted, readonly=True)
		_status, found = server.imap.uid("search", None, plan.criteria)
		uids = new_uids(found[0] if found else None, plan.start)
		self.flags.folder_progress[folder.folder_name] = FolderState(
			state.uidvalidity, progress_start(plan, uids, state)
		)
		for uid in uids:
			mail = self.fetch_mail(server, uid, folder)
			if mail:
				yield mail
			self.flags.folder_progress[folder.folder_name] = FolderState(state.uidvalidity, uid + 1)

	def fetch_mail(self, server, uid: int, folder) -> InboundMail | None:
		status, data = server.imap.uid("fetch", str(uid), "(BODY.PEEK[] FLAGS)")
		raw, seen_status = parse_fetch(data if status == "OK" else None)
		if raw is None:
			self.log_error(
				title=_("Unable to fetch email"), message=f"{self.name}: {folder.folder_name} UID {uid}"
			)
			return None
		try:
			return InboundMail(raw, self, str(uid), seen_status, folder.append_to)
		except Exception:
			self.handle_bad_emails(str(uid), raw, frappe.get_traceback())
			return None

	def mailbox_row(self) -> dict:
		if self.flags.mailbox_row is None:
			self.flags.mailbox_row = (
				frappe.db.get_value(
					"Mail Forward Mailbox",
					{"parenttype": SETTINGS, "email_account": self.name},
					["name", "forward_since", "last_mail_check"],
					as_dict=True,
				)
				or {}
			)
		return self.flags.mailbox_row

	def reread_since(self):
		row = self.mailbox_row()
		moment = row.get("last_mail_check") or row.get("forward_since")
		return get_datetime(moment).date() if moment else None

	def save_folder_progress(self):
		progress = self.flags.folder_progress or {}
		for folder_name, state in progress.items():
			frappe.db.set_value(
				"IMAP Folder",
				{"parent": self.name, "parenttype": "Email Account", "folder_name": folder_name},
				{"uidvalidity": state.uidvalidity, "uidnext": str(state.uidnext)},
				update_modified=False,
			)
		row = self.mailbox_row()
		if progress and row.get("name") and self.flags.mail_check_started:
			frappe.db.set_value(
				"Mail Forward Mailbox",
				row["name"],
				"last_mail_check",
				self.flags.mail_check_started,
				update_modified=False,
			)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
