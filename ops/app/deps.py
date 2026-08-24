"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from . import sessions
from .sessions import COOKIE_NAME, Session


class LoginRequired(HTTPException):
	"""Raised instead of returning a 401 body, so the handler can redirect a
	full page load but leave an htmx fragment request as a 401."""

	def __init__(self) -> None:
		super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")


def current_session(request: Request) -> Session:
	session = sessions.get(request.cookies.get(COOKIE_NAME))
	if session is None:
		raise LoginRequired()
	return session


SessionDep = Annotated[Session, Depends(current_session)]


def require_csrf(request: Request, session: SessionDep) -> Session:
	token = request.headers.get("x-csrf-token") or ""
	if not token:
		# Form posts carry it in a hidden field; header is what htmx sends.
		token = getattr(request.state, "form_csrf", "") or ""
	if token != session.csrf:
		raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad or missing CSRF token")
	return session


def client_ip(request: Request) -> str:
	forwarded = request.headers.get("x-forwarded-for", "")
	if forwarded:
		return forwarded.split(",")[0].strip()
	return request.client.host if request.client else "unknown"


def login_redirect(request: Request) -> RedirectResponse:
	nxt = request.url.path
	return RedirectResponse(f"/login?next={nxt}", status_code=status.HTTP_303_SEE_OTHER)
