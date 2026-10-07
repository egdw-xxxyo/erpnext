from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime

from erpnext.correspondence.doctype.mail_forward_settings import mail_forward_settings
from erpnext.correspondence.imap_folders import parse_list_response
from erpnext.correspondence.imap_uids import FolderState
from erpnext.correspondence.mail_forward import (
	PROCESSED_FIELD,
	check_forwarding_health,
	forward_communication,
	sync_delivery_status,
)

WATCHED = "_Test Watched Mailbox"
SENDER = "_Test Forward Sender"


def make_account(name: str, email: str, **values):
	if frappe.db.exists("Email Account", name):
		frappe.delete_doc("Email Account", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": name,
			"email_id": email,
			"password": "secret",
			"email_server": "imap.example.com",
			"smtp_server": "smtp.example.com",
			**values,
		}
	).insert(ignore_permissions=True)


def make_recipient(code: str, email: str | None, enabled: int = 1):
	frappe.delete_doc("Mail Forward Recipient", code, force=True, ignore_missing=True)
	return frappe.get_doc(
		{"doctype": "Mail Forward Recipient", "code": code, "role": code, "email": email, "enabled": enabled}
	).insert(ignore_permissions=True)


def make_rule(description: str, patterns: str, codes):
	return frappe.get_doc(
		{
			"doctype": "Mail Forward Rule",
			"description": description,
			"sender_patterns": patterns,
			"recipients": [{"recipient": code} for code in codes],
		}
	).insert(ignore_permissions=True)


def receive(sender: str, message_id: str, days_ago: int = 0, email_account: str = WATCHED):
	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"email_account": email_account,
			"sender": sender,
			"sender_full_name": "Bank Manager",
			"recipients": "watched@kalheon.test",
			"subject": "Statement for September",
			"content": "<p>Please find the statement attached.</p>",
			"communication_date": add_days(now_datetime(), -days_ago),
			"message_id": message_id,
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "statement.txt",
			"attached_to_doctype": "Communication",
			"attached_to_name": comm.name,
			"is_private": 1,
			"content": b"balance: 42",
		}
	).insert(ignore_permissions=True)
	return comm


def logs_for(comm):
	return frappe.get_all(
		"Mail Forward Log",
		filters={"communication": comm.name},
		fields=["recipient", "email", "status", "note", "email_queue", "rules"],
		order_by="recipient asc",
	)


class MailForwardCase(FrappeTestCase):
	def setUp(self):
		make_account(
			WATCHED,
			"watched@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX"}],
		)
		make_account(SENDER, "robot@kalheon.test", enable_outgoing=1)
		make_recipient("_FIN", "fin@kalheon.test")
		make_recipient("_HR", "hr@kalheon.test")
		make_recipient("_BOSS", "FIN@kalheon.test ")
		make_recipient("_EMPTY", None)
		make_rule("Bank", "@bank.test", ["_FIN", "_BOSS"])
		make_rule("Court", "@court.test", ["_FIN", "_HR", "_EMPTY"])
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 1
		settings.sender_account = SENDER
		settings.set(
			"mailboxes",
			[
				{
					"email_account": WATCHED,
					"folder_mode": "Manual",
					"forward_since": add_days(now_datetime(), -1),
				}
			],
		)
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()


class TestMailForward(MailForwardCase):
	def test_known_sender_gets_one_copy_per_address_with_attachments(self):
		comm = receive("manager@bank.test", "<m1@bank.test>")
		forward_communication(comm.name)
		logs = logs_for(comm)
		self.assertEqual([(log.email, log.status) for log in logs], [("fin@kalheon.test", "Queued")])
		queue = frappe.get_doc("Email Queue", logs[0].email_queue)
		self.assertEqual(queue.sender, "robot@kalheon.test")
		self.assertEqual([row.recipient for row in queue.recipients], ["fin@kalheon.test"])
		self.assertEqual(
			[row["fid"] for row in frappe.parse_json(queue.attachments)],
			frappe.get_all("File", filters={"attached_to_name": comm.name}, pluck="name"),
		)
		self.assertIn("manager@bank.test", queue.message)
		self.assertIn("watched@kalheon.test", queue.message)
		self.assertIn("Auto-Submitted: auto-generated", queue.message)

	def test_unknown_sender_is_ignored(self):
		comm = receive("friend@example.test", "<m2@example.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_recipient_without_email_is_logged_as_skipped(self):
		comm = receive("judge@court.test", "<m3@court.test>")
		forward_communication(comm.name)
		self.assertEqual(
			[(log.recipient, log.status) for log in logs_for(comm)],
			[("_EMPTY", "Skipped"), ("_FIN", "Queued"), ("_HR", "Queued")],
		)

	def test_running_twice_sends_nothing_new(self):
		comm = receive("manager@bank.test", "<m4@bank.test>")
		forward_communication(comm.name)
		forward_communication(comm.name)
		self.assertEqual(len(logs_for(comm)), 1)

	def test_mail_older_than_the_mailbox_is_not_forwarded(self):
		comm = receive("manager@bank.test", "<m5@bank.test>", days_ago=3)
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_own_address_as_sender_is_ignored(self):
		comm = receive("robot@kalheon.test", "<m6@kalheon.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])

	def test_rule_matching_an_own_address_is_refused(self):
		self.assertRaises(frappe.ValidationError, make_rule, "Loop", "@kalheon.test", ["_FIN"])

	def test_watched_mailbox_is_switched_to_safe_settings(self):
		frappe.db.set_value(
			"Email Account",
			WATCHED,
			{"email_sync_option": "UNSEEN", "create_contact": 1, "enable_auto_reply": 1},
		)
		frappe.get_single("Mail Forward Settings").save()
		self.assertEqual(
			frappe.db.get_value(
				"Email Account", WATCHED, ["email_sync_option", "create_contact", "enable_auto_reply"]
			),
			("ALL", 0, 0),
		)

	def test_watched_mailbox_cannot_be_switched_back_to_unseen(self):
		account = frappe.get_doc("Email Account", WATCHED)
		account.email_sync_option = "UNSEEN"
		account.save()
		self.assertEqual(frappe.db.get_value("Email Account", WATCHED, "email_sync_option"), "ALL")

	def test_sender_account_sends_without_tracking(self):
		self.assertEqual(
			frappe.db.get_value("Email Account", SENDER, ["track_email_status", "send_unsubscribe_message"]),
			(0, 0),
		)

	def test_forwarding_accounts_carry_their_form_profile(self):
		def profile(name):
			account = frappe.get_doc("Email Account", name)
			account.run_method("onload")
			return account.get_onload().get("mail_forwarding")

		self.assertEqual(profile(WATCHED)["role"], "Watched")
		self.assertIn("email_sync_option", profile(WATCHED)["locked"])
		self.assertEqual(profile(WATCHED)["hidden"], ("initial_sync_count",))
		self.assertEqual(profile(SENDER)["role"], "Sender")
		make_account("_Test Unrelated", "unrelated@kalheon.test", enable_outgoing=1)
		self.assertIsNone(profile("_Test Unrelated"))

	def test_sender_sharing_the_watched_address_is_refused(self):
		make_account("_Test Watched SMTP", "Watched@Kalheon.test", enable_outgoing=1)
		settings = frappe.get_single("Mail Forward Settings")
		settings.sender_account = "_Test Watched SMTP"
		self.assertRaises(frappe.ValidationError, settings.save)

	def test_delivery_outcome_comes_from_the_email_queue(self):
		comm = receive("judge@court.test", "<m8@court.test>")
		forward_communication(comm.name)
		fin, hr = (log for log in logs_for(comm) if log.status == "Queued")
		frappe.db.set_value("Email Queue", fin.email_queue, "status", "Sent")
		frappe.db.set_value(
			"Email Queue", hr.email_queue, {"status": "Error", "error": "550 mailbox unavailable"}
		)
		sync_delivery_status()
		logs = {log.recipient: log for log in logs_for(comm)}
		self.assertEqual(
			{code: log.status for code, log in logs.items()},
			{"_EMPTY": "Skipped", "_FIN": "Sent", "_HR": "Failed"},
		)
		self.assertIsNone(logs["_FIN"].note)
		self.assertEqual(logs["_HR"].note, "550 mailbox unavailable")

	def test_mail_still_in_the_queue_stays_queued(self):
		comm = receive("manager@bank.test", "<m9@bank.test>")
		forward_communication(comm.name)
		sync_delivery_status()
		self.assertEqual([log.status for log in logs_for(comm)], ["Queued"])

	def test_disabled_forwarding_does_nothing(self):
		frappe.db.set_single_value("Mail Forward Settings", "enabled", 0)
		comm = receive("manager@bank.test", "<m7@bank.test>")
		forward_communication(comm.name)
		self.assertEqual(logs_for(comm), [])


def arrived(comm, hours_ago: int):
	frappe.db.set_value(
		"Communication",
		comm.name,
		"creation",
		add_to_date(now_datetime(), hours=-hours_ago),
		update_modified=False,
	)


def make_manager(email: str):
	frappe.delete_doc("User", email, force=True, ignore_missing=True)
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Mail",
			"send_welcome_email": 0,
			"roles": [{"role": "Correspondence Manager"}],
		}
	).insert(ignore_permissions=True)


def alerts_for(user: str):
	return frappe.get_all(
		"Notification Log",
		filters={"for_user": user, "document_type": "Mail Forward Settings"},
		fields=["subject", "link", "type"],
	)


class TestMailForwardHealth(MailForwardCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("Mail Forward Settings", "enabled_since", add_days(now_datetime(), -2))
		frappe.db.set_single_value(
			"Mail Forward Settings", "last_health_check", add_to_date(now_datetime(), hours=-1)
		)

	def processed(self, comm):
		return frappe.db.get_value("Communication", comm.name, PROCESSED_FIELD)

	def test_mail_without_copies_is_still_marked_processed(self):
		comm = receive("friend@example.test", "<h1@example.test>")
		forward_communication(comm.name)
		self.assertEqual(self.processed(comm), 1)

	def test_lost_mail_is_forwarded_by_the_hourly_check(self):
		comm = receive("manager@bank.test", "<h2@bank.test>")
		arrived(comm, 2)
		check_forwarding_health()
		self.assertEqual([log.email for log in logs_for(comm)], ["fin@kalheon.test"])
		self.assertEqual(self.processed(comm), 1)

	def test_mail_younger_than_an_hour_is_left_to_its_own_job(self):
		comm = receive("manager@bank.test", "<h3@bank.test>")
		check_forwarding_health()
		self.assertEqual(logs_for(comm), [])

	def test_mail_older_than_the_window_is_not_picked_up(self):
		frappe.db.set_single_value("Mail Forward Settings", "enabled_since", add_days(now_datetime(), -10))
		comm = receive("manager@bank.test", "<h4@bank.test>")
		arrived(comm, 24 * 4)
		check_forwarding_health()
		self.assertEqual(logs_for(comm), [])

	def test_mail_from_before_forwarding_was_enabled_is_not_picked_up(self):
		frappe.db.set_single_value("Mail Forward Settings", "enabled_since", now_datetime())
		comm = receive("manager@bank.test", "<h5@bank.test>")
		arrived(comm, 2)
		check_forwarding_health()
		self.assertEqual(logs_for(comm), [])

	def test_a_rule_added_later_does_not_resend_processed_mail(self):
		comm = receive("clerk@later.test", "<h6@later.test>")
		forward_communication(comm.name)
		arrived(comm, 2)
		make_rule("Later", "@later.test", ["_FIN"])
		check_forwarding_health()
		self.assertEqual(logs_for(comm), [])

	def test_an_email_filled_in_later_does_not_resend_processed_mail(self):
		comm = receive("judge@court.test", "<h7@court.test>")
		forward_communication(comm.name)
		arrived(comm, 2)
		frappe.db.set_value("Mail Forward Recipient", "_EMPTY", "email", "empty@kalheon.test")
		check_forwarding_health()
		self.assertNotIn("empty@kalheon.test", [log.email for log in logs_for(comm)])

	def test_disabled_forwarding_picks_nothing_up(self):
		frappe.db.set_single_value("Mail Forward Settings", "enabled", 0)
		comm = receive("manager@bank.test", "<h8@bank.test>")
		arrived(comm, 2)
		check_forwarding_health()
		self.assertEqual(logs_for(comm), [])

	def test_turning_forwarding_on_moves_the_boundary_to_now(self):
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 0
		settings.save(ignore_permissions=True)
		settings.enabled = 1
		settings.save(ignore_permissions=True)
		self.assertGreater(get_datetime(settings.enabled_since), add_to_date(now_datetime(), minutes=-1))

	def test_saving_enabled_settings_keeps_the_boundary(self):
		since = add_days(now_datetime(), -2).replace(microsecond=0)
		frappe.db.set_single_value("Mail Forward Settings", "enabled_since", since)
		settings = frappe.get_single("Mail Forward Settings")
		settings.save(ignore_permissions=True)
		self.assertEqual(get_datetime(settings.enabled_since), since)

	def test_failures_are_reported_once_to_managers(self):
		manager = make_manager("_mail-manager@kalheon.test")
		comm = receive("manager@bank.test", "<h9@bank.test>")
		forward_communication(comm.name)
		frappe.db.set_value("Mail Forward Log", {"communication": comm.name}, "status", "Failed")
		check_forwarding_health()
		alerts = alerts_for(manager.name)
		self.assertEqual(len(alerts), 1)
		self.assertEqual(alerts[0].type, "Alert")
		self.assertIn("Copies that failed to send: 1", alerts[0].subject)
		self.assertEqual(alerts[0].link, "/desk/mail-forward-log")
		check_forwarding_health()
		self.assertEqual(len(alerts_for(manager.name)), 1)

	def test_quiet_hour_sends_no_alert(self):
		manager = make_manager("_mail-quiet@kalheon.test")
		frappe.db.set_single_value("Mail Forward Settings", "last_health_check", now_datetime())
		check_forwarding_health()
		self.assertEqual(alerts_for(manager.name), [])


SECOND = "_Test Second Mailbox"
SERVER_FOLDERS = parse_list_response(
	[
		b'(\\HasNoChildren \\Inbox) "/" Inbox',
		b'(\\HasNoChildren \\Sent) "/" Sent',
		b'(\\HasNoChildren) "/" Banks',
		b'(\\HasNoChildren) "/" "&BBEEMAQ9BDoEOA-"',
		b'(\\HasNoChildren) "/" Spam',
	]
)


def fake_fetch(account):
	if account.name == SECOND:
		raise ConnectionError("server down")
	return SERVER_FOLDERS


def fake_states(account, names):
	return {name: FolderState("5", 40) for name in names}


@contextmanager
def fake_server():
	with (
		patch.object(mail_forward_settings, "fetch_folders", fake_fetch),
		patch.object(mail_forward_settings, "fetch_states", fake_states),
	):
		yield


class TestFolderSync(FrappeTestCase):
	def setUp(self):
		make_account(
			WATCHED,
			"watched@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX", "uidvalidity": "77", "uidnext": "1200"}],
		)
		make_account(
			SECOND,
			"second@kalheon.test",
			enable_incoming=1,
			use_imap=1,
			email_sync_option="ALL",
			imap_folder=[{"folder_name": "INBOX"}],
		)
		settings = frappe.get_single("Mail Forward Settings")
		settings.enabled = 0
		settings.set(
			"mailboxes",
			[
				{"email_account": WATCHED, "folder_mode": "All Folders"},
				{"email_account": SECOND, "folder_mode": "All Folders"},
			],
		)
		settings.save(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_user_folders_are_added_and_known_ones_keep_their_sync_state(self):
		with fake_server():
			results = mail_forward_settings.sync_all_mailboxes()
		folders = frappe.get_doc("Email Account", WATCHED).imap_folder
		self.assertEqual([row.folder_name for row in folders], ["INBOX", "Banks", "&BBEEMAQ9BDoEOA-"])
		self.assertEqual((folders[0].uidvalidity, folders[0].uidnext), ("77", "1200"))
		self.assertEqual({(row.uidvalidity, row.uidnext) for row in folders[1:]}, {("5", "40")})
		self.assertIsNone(results[WATCHED])
		self.assertIn("server down", results[SECOND])

	def test_sync_now_reports_readable_folder_names(self):
		with fake_server():
			results = {row["email_account"]: row for row in mail_forward_settings.sync_folders_now()}
		self.assertEqual(results[WATCHED]["folders"], ["INBOX", "Banks", "Банки"])
		self.assertTrue(results[SECOND]["error"])

	def test_a_failing_mailbox_keeps_its_folders_and_records_the_error(self):
		with fake_server():
			mail_forward_settings.sync_all_mailboxes()
		self.assertEqual(
			[row.folder_name for row in frappe.get_doc("Email Account", SECOND).imap_folder], ["INBOX"]
		)
		row = frappe.get_all(
			"Mail Forward Mailbox",
			filters={"email_account": SECOND},
			fields=["folder_sync_error", "last_folder_sync"],
		)[0]
		self.assertIn("server down", row.folder_sync_error)
		self.assertTrue(row.last_folder_sync)

	def test_manual_mailbox_keeps_its_folders_and_gets_a_starting_point(self):
		frappe.db.set_value("Mail Forward Mailbox", {"email_account": WATCHED}, "folder_mode", "Manual")
		self.set_inbox(None, None)
		with fake_server():
			mail_forward_settings.sync_all_mailboxes()
		folders = frappe.get_doc("Email Account", WATCHED).imap_folder
		self.assertEqual(
			[(row.folder_name, row.uidvalidity, row.uidnext) for row in folders], [("INBOX", "5", "40")]
		)

	def test_only_new_mailboxes_are_synced_after_saving(self):
		frappe.db.set_value(
			"Mail Forward Mailbox", {"email_account": WATCHED}, "last_folder_sync", now_datetime()
		)
		with fake_server():
			results = mail_forward_settings.sync_new_mailboxes()
		self.assertEqual(list(results), [SECOND])

	def test_adding_a_mailbox_queues_its_folder_sync(self):
		with patch.object(mail_forward_settings.frappe, "enqueue") as enqueue:
			frappe.get_single("Mail Forward Settings").save(ignore_permissions=True)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.args[0], mail_forward_settings.SYNC_JOB)

	def set_inbox(self, uidvalidity, uidnext):
		frappe.db.set_value(
			"IMAP Folder",
			{"parent": WATCHED, "folder_name": "INBOX"},
			{"uidvalidity": uidvalidity, "uidnext": uidnext},
		)
