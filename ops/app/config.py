"""Environment-driven settings for the ops dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
	try:
		return int(os.environ.get(name, "") or default)
	except ValueError:
		return default


def _list(name: str) -> list[str]:
	raw = os.environ.get(name, "") or ""
	return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
	ssh_host: str = field(default_factory=lambda: os.environ.get("OPS_SSH_HOST", "host.docker.internal"))
	ssh_port: int = field(default_factory=lambda: _int("OPS_SSH_PORT", 22))
	repo_path: str = field(default_factory=lambda: os.environ.get("OPS_REPO_PATH", "/home/mpa/git/erpnext"))
	site: str = field(default_factory=lambda: os.environ.get("OPS_SITE", "frontend"))
	compose_project: str = field(default_factory=lambda: os.environ.get("OPS_COMPOSE_PROJECT", "docker"))
	erp_url: str = field(default_factory=lambda: os.environ.get("OPS_ERP_URL", "http://127.0.0.1:8080"))

	allowed_users: list[str] = field(default_factory=lambda: _list("OPS_ALLOWED_USERS"))
	session_secret: str = field(default_factory=lambda: os.environ.get("OPS_SESSION_SECRET", ""))
	session_ttl: int = field(default_factory=lambda: _int("OPS_SESSION_TTL", 3600))
	session_idle: int = field(default_factory=lambda: _int("OPS_SESSION_IDLE", 1800))

	backup_keep: int = field(default_factory=lambda: _int("OPS_BACKUP_KEEP", 5))
	env_label: str = field(default_factory=lambda: os.environ.get("OPS_ENV_LABEL", "dev"))

	data_dir: str = field(default_factory=lambda: os.environ.get("OPS_DATA_DIR", "/data"))
	# Renders every panel from fixtures so templates can be worked on with no
	# host to SSH into. Never set this on a server.
	fake_host: bool = field(default_factory=lambda: os.environ.get("OPS_FAKE_HOST", "") == "1")

	@property
	def jobs_dir(self) -> str:
		return f"{self.repo_path}/.ops-jobs"

	@property
	def is_prod(self) -> bool:
		return self.env_label.lower() == "prod"


settings = Settings()

if not settings.session_secret and not settings.fake_host:
	raise RuntimeError("OPS_SESSION_SECRET is required. Generate one with: openssl rand -hex 32")
