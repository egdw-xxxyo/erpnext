from collections.abc import Iterator
from contextlib import suppress

import frappe
from frappe import _
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.email.receive import InboundMail
from frappe.utils import cint

from erpnext.correspondence.imap_uids import FolderState, first_uid, new_uids, parse_fetch, parse_status


class ForwardingEmailAccount(EmailAccount):
	def reads_folders_by_uid(self) -> bool:
		return bool(
			self.enable_incoming
			and self.use_imap
			and self.email_sync_option == "ALL"
			and self.service != "Frappe Mail"
			and frappe.db.exists(
				"Mail Forward Mailbox", {"parenttype": "Mail Forward Settings", "email_account": self.name}
			)
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
		start = first_uid(folder.uidvalidity, folder.uidnext, state, cint(self.initial_sync_count) or 100)
		self.flags.folder_progress[folder.folder_name] = FolderState(state.uidvalidity, start)
		server.imap.select(quoted, readonly=True)
		_status, found = server.imap.uid("search", None, f"UID {start}:*")
		for uid in new_uids(found[0] if found else None, start):
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

	def save_folder_progress(self):
		for folder_name, state in (self.flags.folder_progress or {}).items():
			frappe.db.set_value(
				"IMAP Folder",
				{"parent": self.name, "parenttype": "Email Account", "folder_name": folder_name},
				{"uidvalidity": state.uidvalidity, "uidnext": str(state.uidnext)},
				update_modified=False,
			)
		frappe.db.commit()
