import imaplib
import re
from datetime import date, datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.correspondence.email_account import ForwardingEmailAccount
from erpnext.correspondence.test_mail_forward import WATCHED, make_account

OTHER = "_Test Unwatched Mailbox"
ARRIVED = date(2026, 10, 2)


def raw_mail(folder: str, uid: int) -> bytes:
	return (
		f"From: manager@bank.test\r\nTo: watched@kalheon.test\r\nSubject: {folder} {uid}\r\n"
		f"Message-ID: <{folder}-{uid}@bank.test>\r\nDate: Fri, 02 Oct 2026 10:00:00 +0300\r\n\r\nBody\r\n"
	).encode()


class FakeImap:
	def __init__(
		self,
		folders: dict[str, tuple[str, list[int]]],
		broken: frozenset = frozenset(),
		unreadable: frozenset = frozenset(),
		arrived: dict | None = None,
	):
		self.folders = folders
		self.broken = broken
		self.unreadable = unreadable
		self.arrived = arrived or {}
		self.selected = None
		self.calls = []

	def status(self, quoted, items):
		validity, uids = self.folders[quoted.strip('"')]
		return "OK", [f"{quoted} (UIDVALIDITY {validity} UIDNEXT {max(uids, default=0) + 1})".encode()]

	def select(self, quoted, readonly=False):
		self.calls.append(("select", quoted, readonly))
		self.selected = quoted.strip('"')
		return "OK", [b"1"]

	def uid(self, command, *args):
		self.calls.append((command, *args))
		uids = self.folders[self.selected][1]
		if command == "search":
			return "OK", [" ".join(map(str, self.search(uids, args[1]))).encode()]
		uid = int(args[0])
		if (self.selected, uid) in self.broken:
			raise imaplib.IMAP4.abort("connection lost")
		if uid not in uids or (self.selected, uid) in self.unreadable:
			return "NO", [None]
		return "OK", [(f"1 (UID {uid} BODY[] {{10}}".encode(), raw_mail(self.selected, uid)), b")"]

	def search(self, uids: list[int], criteria: str) -> list[int]:
		if criteria.startswith("SINCE "):
			since = datetime.strptime(criteria[6:], "%d-%b-%Y").date()
			return [uid for uid in uids if self.arrived.get((self.selected, uid), ARRIVED) >= since]
		start = int(re.search(r"UID (\d+):\*", criteria)[1])
		return [uid for uid in uids if uid >= start] or uids[-1:]

	def logout(self):
		self.calls.append(("logout",))


class FakeServer:
	def __init__(self, imap):
		self.imap = imap


class TestFolderUids(FrappeTestCase):
	def setUp(self):
		make_account(
			WATCHED,
			"watched@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			initial_sync_count="100",
			imap_folder=[
				{"folder_name": "INBOX", "uidvalidity": "7", "uidnext": "500"},
				{"folder_name": "Banks", "uidvalidity": "3", "uidnext": "10"},
			],
		)
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 0
		settings.set("mailboxes", [{"email_account": WATCHED, "folder_mode": "Manual"}])
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def pull(self, imap):
		account = frappe.get_doc("Email Account", WATCHED)
		account.flags.folder_progress = {}
		with patch.object(ForwardingEmailAccount, "get_incoming_server", return_value=FakeServer(imap)):
			mails = account.get_inbound_mails()
		with patch.object(frappe.db, "commit"):
			account.save_folder_progress()
		return [mail.subject for mail in mails]

	def set_folder(self, folder_name: str, uidvalidity, uidnext):
		frappe.db.set_value(
			"IMAP Folder",
			{"parent": WATCHED, "folder_name": folder_name},
			{"uidvalidity": uidvalidity, "uidnext": uidnext},
		)

	def mailbox(self, field: str):
		return frappe.db.get_value("Mail Forward Mailbox", {"email_account": WATCHED}, field)

	def stored(self):
		return {
			row.folder_name: (row.uidvalidity, row.uidnext)
			for row in frappe.get_doc("Email Account", WATCHED).imap_folder
		}

	def test_each_folder_is_read_from_its_own_uid(self):
		imap = FakeImap({"INBOX": ("7", [499, 500, 501]), "Banks": ("3", [9, 10])})
		self.assertEqual(self.pull(imap), ["INBOX 500", "INBOX 501", "Banks 10"])
		self.assertEqual(self.stored(), {"INBOX": ("7", "502"), "Banks": ("3", "11")})
		self.assertTrue(all(call[2] for call in imap.calls if call[0] == "select"))
		self.assertFalse([call for call in imap.calls if call[0] in ("STORE", "store")])

	def test_nothing_new_fetches_nothing(self):
		imap = FakeImap({"INBOX": ("7", [499]), "Banks": ("3", [9])})
		self.assertEqual(self.pull(imap), [])
		self.assertFalse([call for call in imap.calls if call[0] == "fetch"])
		self.assertEqual(self.stored(), {"INBOX": ("7", "500"), "Banks": ("3", "10")})

	def test_new_folder_skips_the_mail_already_there(self):
		self.set_folder("Banks", None, None)
		imap = FakeImap({"INBOX": ("7", [500]), "Banks": ("3", [8, 9, 10])})
		self.assertEqual(self.pull(imap), ["INBOX 500"])
		self.assertEqual(self.stored()["Banks"], ("3", "11"))
		imap.folders["Banks"] = ("3", [8, 9, 10, 11])
		self.assertEqual(self.pull(imap), ["Banks 11"])

	def test_renumbered_folder_rereads_mail_since_the_last_check(self):
		frappe.db.set_value(
			"Mail Forward Mailbox", {"email_account": WATCHED}, "last_mail_check", "2026-10-02 10:00:00"
		)
		arrived = {("INBOX", 50): date(2026, 9, 1), ("INBOX", 250): date(2026, 10, 1)}
		imap = FakeImap({"INBOX": ("8", [50, 250, 260]), "Banks": ("3", [])}, arrived=arrived)
		self.assertEqual(self.pull(imap), ["INBOX 250", "INBOX 260"])
		self.assertEqual(self.stored()["INBOX"], ("8", "261"))
		self.assertIn(("search", None, "SINCE 01-Oct-2026"), imap.calls)

	def test_a_pass_records_when_the_mail_was_checked(self):
		self.assertIsNone(self.mailbox("last_mail_check"))
		self.pull(FakeImap({"INBOX": ("7", [499]), "Banks": ("3", [9])}))
		self.assertIsNotNone(self.mailbox("last_mail_check"))

	def test_lost_connection_keeps_the_counter_at_the_last_read_mail(self):
		imap = FakeImap({"INBOX": ("7", [500, 501, 502]), "Banks": ("3", [10])}, frozenset({("INBOX", 501)}))
		with patch.object(ForwardingEmailAccount, "log_error"):
			self.assertEqual(self.pull(imap), ["INBOX 500"])
		self.assertEqual(self.stored(), {"INBOX": ("7", "501"), "Banks": ("3", "10")})

	def test_unreadable_mail_is_logged_and_skipped(self):
		imap = FakeImap(
			{"INBOX": ("7", [500, 502]), "Banks": ("3", [])}, unreadable=frozenset({("INBOX", 500)})
		)
		with patch.object(ForwardingEmailAccount, "log_error") as log_error:
			self.assertEqual(self.pull(imap), ["INBOX 502"])
		log_error.assert_called_once()
		self.assertEqual(self.stored()["INBOX"], ("7", "503"))

	def test_receive_stores_mail_and_the_counters(self):
		imap = FakeImap({"INBOX": ("7", [500]), "Banks": ("3", [10])})
		account = frappe.get_doc("Email Account", WATCHED)
		with (
			patch.object(ForwardingEmailAccount, "get_incoming_server", return_value=FakeServer(imap)),
			patch.object(frappe.db, "commit"),
		):
			account.receive()
		self.assertEqual(
			sorted(frappe.get_all("Communication", filters={"email_account": WATCHED}, pluck="subject")),
			["Banks 10", "INBOX 500"],
		)
		self.assertEqual(self.stored(), {"INBOX": ("7", "501"), "Banks": ("3", "11")})

	def test_unwatched_account_keeps_the_frappe_behaviour(self):
		make_account(
			OTHER,
			"other@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX"}],
		)
		self.assertFalse(frappe.get_doc("Email Account", OTHER).reads_folders_by_uid())
		self.assertTrue(frappe.get_doc("Email Account", WATCHED).reads_folders_by_uid())
