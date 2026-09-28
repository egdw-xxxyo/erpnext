"""Running part of a request as another user without logging the caller out.

`frappe.set_user` does more than change the user: it points `session.sid` at the user name and
empties `session.data`. At the end of the request `Session.update()` writes `frappe.session`
back into the session cache under the caller's real sid — so after a plain
`set_user(other)` … `set_user(caller)` round trip the cached session has no user, and the next
request from that browser or phone fails with "User None not found" and lands on the login page.
"""

from contextlib import contextmanager

import frappe


@contextmanager
def preserved_session():
	"""Put the caller's session back exactly as it was, whatever the block did to the user."""
	session = frappe.local.session
	user, sid, data = session.user, session.sid, session.data
	try:
		yield
	finally:
		frappe.set_user(user)
		session.sid = sid
		session.data = data


@contextmanager
def acting_as(user):
	"""Run the block as `user`, then hand the request back to the caller's own session."""
	with preserved_session():
		frappe.set_user(user)
		yield
