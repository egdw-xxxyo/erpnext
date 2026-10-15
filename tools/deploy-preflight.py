#!/usr/bin/env python3
"""Pre-flight gate of `./deploy live`: is this release safe to roll out under live traffic?

"Safe" means additive in every dimension. While the new release is being rolled out the
previous one keeps serving against the already migrated database, and a rollback puts the
previous code back on top of the new schema. Both only work when nothing the old code
relies on was removed, renamed or rewritten. Every check fails closed: it passes on a
mechanical proof and refuses otherwise, and a refusal means "use ./deploy build in a
window", not "something is broken".

Reads git and the directory of raw facts ./deploy collected from the running site
(preflight_facts there): the deployed-release record, the patch log, table sizes, installed
apps, remote heads of the extra apps, free space.

Exit 0 = online-safe, 3 = refused. One PASS/REFUSE line per check.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIG_TABLE_BYTES = 1 << 30
HEADROOM_BYTES = 200 << 20

DDL_RE = re.compile(
	r"\b(drop\s+(table|column|index|key)|truncate\s|alter\s+table|rename\s+(table|column))", re.I
)
WRITE_RE = re.compile(r"^\s*(update|delete)\b", re.I)
# Calls that change or remove what the previous release may still read.
FORBIDDEN_CALLS = {
	"frappe.db.sql_ddl",
	"frappe.rename_doc",
	"frappe.db.change_column_type",
	"frappe.db.delete",
	"frappe.db.truncate",
	"frappe.db.rename_table",
	"frappe.db.rename_column",
	"frappe.model.rename_field.rename_field",
	"rename_field",
	"frappe.reload_doctype",
	"frappe.qb.update",
	"frappe.db.set_value",
	"frappe.db.multisql",
}
DELETE_DOC_TARGETS = {"DocType", "Custom Field", "Property Setter"}
# fieldtype changes that keep every stored value readable by the old code
WIDENINGS = {
	("Data", "Small Text"),
	("Data", "Text"),
	("Data", "Long Text"),
	("Small Text", "Text"),
	("Small Text", "Long Text"),
	("Text", "Long Text"),
	("Int", "Float"),
}
NO_COLUMN_TYPES = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"HTML",
	"Button",
	"Heading",
	"Image",
	"Fold",
	"Table",
	"Table MultiSelect",
}


def git(*args, cwd=REPO, check=True):
	result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
	if check and result.returncode != 0:
		raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
	return result.stdout


def show(sha, path, cwd=REPO):
	result = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=cwd, capture_output=True, text=True)
	return result.stdout if result.returncode == 0 else None


class Gate:
	def __init__(self, facts):
		self.facts = facts
		self.deployed = facts.get("deployed") or {}
		self.refused = []
		self.new_columns = []  # (doctype or None, fieldname, wants_index)
		self.base = self.deployed.get("erpnext_sha")
		self.frappe_dir = os.path.join(REPO, "frappe")
		self.frappe_base = self.deployed.get("frappe_sha")

	def report(self, check, ok, text):
		print(f"{'PASS  ' if ok else 'REFUSE'} {check:<4} {text}")
		if not ok:
			self.refused.append(check)

	def run(self):
		self.g0_clean_tagged()
		if not self.g1_deployed_known():
			for check in ("G2", "G3", "G4", "G5", "G8", "G9"):
				self.report(check, False, "not evaluated: no known deployed release to diff against")
		else:
			modules = self.g2_g4_patches()
			self.g3_patch_code(modules)
			self.g5_doctype_json()
			self.collect_custom_fields()
			self.g8_alter_cost()
			self.g9_hooks()
		self.g6_apps()
		self.g7_assets()
		self.g10_site_config()
		self.g11_headroom()
		return 3 if self.refused else 0

	# -- G0 / G1 -----------------------------------------------------------------

	def g0_clean_tagged(self):
		# Untracked files count only where the image build would pick them up: a host
		# keeps backups of its own config next to the repo files, and those are not a release.
		dirty = (
			git("status", "--porcelain", "-uno").strip()
			+ "\n"
			+ git("status", "--porcelain", "--untracked-files=all", "--", "erpnext").strip()
		).strip()
		dirty = "\n".join(sorted(set(dirty.splitlines())))
		tag = git("describe", "--tags", "--exact-match", "HEAD", check=False).strip()
		if dirty:
			self.report(
				"G0", False, f"working tree has uncommitted changes ({len(dirty.splitlines())} paths)"
			)
		elif not tag:
			self.report(
				"G0", False, "HEAD carries no tag — a live deploy ships a release, not a working state"
			)
		else:
			self.report("G0", True, f"clean tree, HEAD is {tag}")

	def g1_deployed_known(self):
		if not self.base:
			self.report(
				"G1", False, "the site has no sites/.deployed-release.json (written by ./deploy build)"
			)
			return False
		if (
			subprocess.run(["git", "merge-base", "--is-ancestor", self.base, "HEAD"], cwd=REPO).returncode
			!= 0
		):
			self.report("G1", False, f"deployed commit {self.base[:10]} is not an ancestor of HEAD")
			return False
		head_frappe = git("rev-parse", "HEAD", cwd=self.frappe_dir).strip()
		if self.frappe_base and (
			subprocess.run(
				["git", "merge-base", "--is-ancestor", self.frappe_base, head_frappe], cwd=self.frappe_dir
			).returncode
			!= 0
		):
			self.report(
				"G1",
				False,
				f"deployed frappe commit {self.frappe_base[:10]} is not an ancestor of the submodule HEAD",
			)
			return False
		count = git("rev-list", "--count", f"{self.base}..HEAD").strip()
		self.report(
			"G1", True, f"deployed {self.deployed.get('tag')} ({self.base[:10]}), {count} commits behind HEAD"
		)
		return True

	# -- patches -----------------------------------------------------------------

	def patch_sources(self):
		sources = [(REPO, self.base, "erpnext/patches.txt", os.path.join(REPO))]
		if self.frappe_base:
			sources.append((self.frappe_dir, self.frappe_base, "frappe/patches.txt", self.frappe_dir))
		return sources

	@staticmethod
	def parse_patches(text):
		section, lines = "pre_model_sync", []
		for raw in (text or "").splitlines():
			line = raw.strip()
			if line.startswith("[") and line.endswith("]"):
				section = line[1:-1]
			elif line and not line.startswith("#"):
				lines.append((section, line))
		return lines

	def g2_g4_patches(self):
		executed = set(self.facts.get("patch_log") or [])
		new, unmarked, pre = [], [], []
		for cwd, base, path, root in self.patch_sources():
			old = {line for _section, line in self.parse_patches(show(base, path, cwd))}
			with open(os.path.join(cwd, path)) as source:
				current = self.parse_patches(source.read())
			for section, line in current:
				if line in old or line in executed:
					continue
				module = line.split()[0].split("#")[0]
				if line.startswith("execute:"):
					new.append((line, None))
					unmarked.append(line)
					continue
				file_path = os.path.join(root, *module.split(".")) + ".py"
				new.append((line, file_path))
				if section == "pre_model_sync":
					pre.append(module)
				if not self.is_marked_safe(file_path):
					unmarked.append(module)
		if unmarked:
			self.report("G2", False, f"new patches without ONLINE_SAFE = True: {', '.join(unmarked[:5])}")
		else:
			self.report("G2", True, f"{len(new)} new patches, all marked ONLINE_SAFE")
		if pre:
			self.report(
				"G4", False, f"new pre_model_sync patches (run against the old schema): {', '.join(pre[:5])}"
			)
		else:
			self.report("G4", True, "no new pre_model_sync patches")
		return [file_path for _line, file_path in new if file_path]

	@staticmethod
	def is_marked_safe(file_path):
		try:
			with open(file_path) as source:
				tree = ast.parse(source.read())
		except (OSError, SyntaxError):
			return False
		names = {}
		for node in tree.body:
			if (
				isinstance(node, ast.Assign)
				and len(node.targets) == 1
				and isinstance(node.targets[0], ast.Name)
			):
				if isinstance(node.value, ast.Constant):
					names[node.targets[0].id] = node.value.value
		return names.get("ONLINE_SAFE") is True and bool(names.get("ONLINE_SAFE_REASON"))

	def g3_patch_code(self, files):
		findings = []
		for file_path in files:
			rel = os.path.relpath(file_path, REPO)
			try:
				with open(file_path) as source:
					tree = ast.parse(source.read())
			except (OSError, SyntaxError) as exc:
				findings.append(f"{rel}: unreadable ({exc})")
				continue
			for node in ast.walk(tree):
				if isinstance(node, ast.Constant) and isinstance(node.value, str):
					if DDL_RE.search(node.value):
						findings.append(f"{rel}:{node.lineno}: DDL in SQL")
					elif WRITE_RE.search(node.value) and not re.search(r"\blimit\b", node.value, re.I):
						findings.append(f"{rel}:{node.lineno}: UPDATE/DELETE without LIMIT")
				elif isinstance(node, ast.Call):
					name = self.call_name(node.func)
					if name in FORBIDDEN_CALLS:
						findings.append(f"{rel}:{node.lineno}: {name}()")
					elif name in ("frappe.delete_doc", "frappe.delete_doc_if_exists") and node.args:
						target = node.args[0]
						if isinstance(target, ast.Constant) and target.value in DELETE_DOC_TARGETS:
							findings.append(f"{rel}:{node.lineno}: {name}({target.value!r})")
					elif name.endswith(".save") or name.endswith(".db_set") or name.endswith(".delete"):
						findings.append(f"{rel}:{node.lineno}: {name}() rewrites existing documents")
		if findings:
			self.report("G3", False, f"{len(findings)} unsafe statements in new patches, e.g. {findings[0]}")
			for finding in findings[1:10]:
				print(f"            {finding}")
		else:
			self.report("G3", True, f"{len(files)} new patch modules, no DDL or unbounded writes")

	@staticmethod
	def call_name(node):
		parts = []
		while isinstance(node, ast.Attribute):
			parts.append(node.attr)
			node = node.value
		if isinstance(node, ast.Name):
			parts.append(node.id)
		return ".".join(reversed(parts))

	# -- schema ------------------------------------------------------------------

	def g5_doctype_json(self):
		problems, added = [], 0
		for cwd, base, prefix in ((REPO, self.base, ""), (self.frappe_dir, self.frappe_base, "frappe/")):
			if not base:
				continue
			changed = git(
				"diff", "--name-status", "--no-renames", base, "HEAD", "--", "*/doctype/*/*.json", cwd=cwd
			)
			for row in changed.splitlines():
				status, path = row.split("\t", 1)
				label = prefix + path
				if os.path.basename(os.path.dirname(path)) + ".json" != os.path.basename(path):
					continue
				if status == "D":
					problems.append(f"{label}: doctype removed")
					continue
				try:
					new = json.loads(show("HEAD", path, cwd) or "")
				except ValueError:
					problems.append(f"{label}: not valid JSON")
					continue
				if status == "A":
					added += 1
					continue
				try:
					old = json.loads(show(base, path, cwd) or "")
				except ValueError:
					problems.append(f"{label}: old version is not valid JSON")
					continue
				problems += [f"{label}: {text}" for text in self.diff_doctype(old, new)]
		if problems:
			self.report("G5", False, f"{len(problems)} non-additive DocType changes, e.g. {problems[0]}")
			for problem in problems[1:10]:
				print(f"            {problem}")
		else:
			self.report(
				"G5",
				True,
				f"DocType JSON changes are additive ({added} new doctypes, {len(self.new_columns)} new columns)",
			)

	def diff_doctype(self, old, new):
		problems = []
		doctype = new.get("name")
		for key in (
			"autoname",
			"naming_rule",
			"istable",
			"issingle",
			"is_submittable",
			"is_tree",
			"is_virtual",
			"engine",
		):
			if old.get(key) != new.get(key):
				problems.append(f"{key} changed")
		old_fields = {
			field.get("fieldname"): field for field in old.get("fields", []) if field.get("fieldname")
		}
		new_fields = {
			field.get("fieldname"): field for field in new.get("fields", []) if field.get("fieldname")
		}
		for name in old_fields.keys() - new_fields.keys():
			problems.append(f"field {name} removed or renamed")
		for name, field in new_fields.items():
			before = old_fields.get(name)
			wants_index = bool(field.get("search_index") or field.get("unique"))
			if before is None:
				if field.get("reqd") and not field.get("default"):
					problems.append(f"new field {name} is mandatory with no default")
				if field.get("unique"):
					problems.append(f"new field {name} is unique")
				if field.get("fieldtype") not in NO_COLUMN_TYPES:
					self.new_columns.append((doctype, name, wants_index))
				continue
			old_type, new_type = before.get("fieldtype"), field.get("fieldtype")
			if old_type != new_type and (old_type, new_type) not in WIDENINGS:
				problems.append(f"field {name}: fieldtype {old_type} -> {new_type}")
			if old_type in ("Link", "Table", "Table MultiSelect", "Dynamic Link") and before.get(
				"options"
			) != field.get("options"):
				problems.append(f"field {name}: options changed")
			if old_type == "Select":
				gone = set((before.get("options") or "").split("\n")) - set(
					(field.get("options") or "").split("\n")
				)
				if gone - {""}:
					problems.append(
						f"field {name}: Select options removed ({', '.join(sorted(gone - {''}))[:60]})"
					)
			for flag in ("unique", "set_only_once", "reqd"):
				if field.get(flag) and not before.get(flag):
					problems.append(f"field {name}: {flag} newly set")
			if (before.get("length") or 0) > (field.get("length") or 0) > 0:
				problems.append(f"field {name}: length reduced")
			if wants_index and not (before.get("search_index") or before.get("unique")):
				self.new_columns.append((doctype, name, True))
		return problems

	def collect_custom_fields(self):
		"""Custom fields added to setup_custom_fields.py. Which doctype a dict belongs to is not
		recoverable from the source in general, so the target stays unknown (None)."""
		path = "erpnext/patches/setup_custom_fields.py"

		def fields(text):
			found = {}
			try:
				tree = ast.parse(text or "")
			except SyntaxError:
				return found
			for node in ast.walk(tree):
				if not isinstance(node, ast.Dict):
					continue
				pairs = {
					key.value: value
					for key, value in zip(node.keys, node.values, strict=False)
					if isinstance(key, ast.Constant) and isinstance(key.value, str)
				}
				name = pairs.get("fieldname")
				if isinstance(name, ast.Constant) and isinstance(name.value, str):
					indexed = any(
						isinstance(pairs.get(flag), ast.Constant) and pairs[flag].value
						for flag in ("search_index", "unique")
					)
					found[name.value] = found.get(name.value, False) or indexed
			return found

		old = fields(show(self.base, path))
		with open(os.path.join(REPO, path)) as source:
			new = fields(source.read())
		for name, indexed in new.items():
			if name not in old or (indexed and not old[name]):
				self.new_columns.append((None, name, indexed))

	def g8_alter_cost(self):
		tables = self.facts.get("tables") or {}
		if not self.new_columns:
			self.report("G8", True, "no new columns or indexes")
			return
		if not tables:
			self.report("G8", False, "table sizes unknown — cannot prove the ALTERs are cheap")
			return
		big = {name: info for name, info in tables.items() if info.get("bytes", 0) >= BIG_TABLE_BYTES}
		problems, lines = [], []
		for doctype, field, wants_index in self.new_columns:
			candidates = {f"tab{doctype}": tables.get(f"tab{doctype}")} if doctype else big
			if doctype and candidates[f"tab{doctype}"] is None:
				continue  # table does not exist yet: the doctype is new
			for table, info in candidates.items():
				size = info.get("bytes", 0)
				note = f"{table} {size >> 20} MB / {info.get('rows', 0)} rows, {field}"
				if size < BIG_TABLE_BYTES:
					lines.append(f"{note} -> small table, OK")
				elif wants_index:
					problems.append(f"{note}: new index on a table over 1 GiB")
				elif (info.get("engine") or "").lower() != "innodb" or (
					info.get("row_format") or ""
				).lower() == "compressed":
					problems.append(
						f"{note}: ADD COLUMN is not instant ({info.get('engine')}/{info.get('row_format')})"
					)
				else:
					lines.append(f"{note} -> INSTANT, OK")
		if problems:
			self.report("G8", False, f"{len(problems)} expensive ALTERs, e.g. {problems[0]}")
		else:
			unknown = sum(1 for doctype, _f, _i in self.new_columns if not doctype)
			self.report(
				"G8",
				True,
				f"{len(self.new_columns)} new columns/indexes ({unknown} custom fields), "
				f"{len(big)} tables over 1 GiB, all ALTERs instant",
			)
		for line in lines[:8]:
			print(f"            {line}")

	# -- hooks / apps / config ---------------------------------------------------

	def g9_hooks(self):
		def hooks(text):
			values = {}
			try:
				tree = ast.parse(text or "")
			except SyntaxError:
				return None
			for node in tree.body:
				if (
					isinstance(node, ast.Assign)
					and len(node.targets) == 1
					and isinstance(node.targets[0], ast.Name)
				):
					if node.targets[0].id in ("before_migrate", "after_migrate"):
						try:
							value = ast.literal_eval(node.value)
						except ValueError:
							return None
						values[node.targets[0].id] = sorted([value] if isinstance(value, str) else value)
			return values

		old = hooks(show(self.base, "erpnext/hooks.py"))
		with open(os.path.join(REPO, "erpnext/hooks.py")) as source:
			new = hooks(source.read())
		if old is None or new is None:
			self.report("G9", False, "erpnext/hooks.py migrate hooks could not be read")
		elif old != new:
			added = sorted(
				{hook for hooks_ in new.values() for hook in hooks_}
				- {hook for hooks_ in old.values() for hook in hooks_}
			)
			self.report(
				"G9", False, f"before_migrate/after_migrate changed: {', '.join(added) or 'entries removed'}"
			)
		else:
			self.report(
				"G9", True, f"migrate hooks unchanged ({sum(len(hooks_) for hooks_ in new.values())} entries)"
			)

	def g6_apps(self):
		try:
			with open(os.path.join(REPO, "apps.json")) as source:
				apps = json.load(source)
		except (OSError, ValueError):
			apps = []
		enabled = {app["name"] for app in apps if app.get("enabled")}
		installed = set(self.facts.get("site_apps") or []) - {"frappe", "erpnext", "insights"}
		recorded = self.deployed.get("apps") or {}
		heads = self.facts.get("app_heads") or {}
		moved = sorted(name for name in heads if not heads[name] or recorded.get(name) != heads[name])
		if enabled != installed:
			self.report(
				"G6", False, f"apps.json enables {sorted(enabled)} but the site has {sorted(installed)}"
			)
		elif self.deployed and self.deployed.get("apps_json_sha") != self.facts.get("apps_json_sha"):
			self.report("G6", False, "apps.json changed since the deployed release")
		elif moved or (apps and not heads):
			self.report(
				"G6",
				False,
				f"extra apps moved since the deployed release: {', '.join(moved) or 'heads unknown'}",
			)
		else:
			self.report("G6", True, f"app set unchanged ({', '.join(sorted(enabled)) or 'no extra apps'})")

	def g7_assets(self):
		# The image does not exist yet when the gate runs; ./deploy checks its manifest right
		# after the build and stops there, before anything on the site is touched.
		self.report("G7", True, "asset manifest of the new image is verified right after it is built")

	def g10_site_config(self):
		if self.deployed and self.deployed.get("site_config_sha") == self.facts.get("site_config_sha"):
			self.report("G10", True, "site-config.json unchanged")
		else:
			self.report("G10", False, "site-config.json differs from the deployed release's")

	def g11_headroom(self):
		free, image = self.facts.get("free_bytes"), self.facts.get("image_bytes")
		if self.facts.get("lean"):
			self.report("G11", False, "lean host (.deploy-lean): two releases cannot exist side by side")
		elif not self.facts.get("db_alive"):
			self.report("G11", False, "the database does not answer")
		elif free is None or image is None:
			self.report("G11", False, "free disk space or image size unknown")
		elif free < HEADROOM_BYTES:
			self.report("G11", False, f"only {free >> 20} MB free")
		else:
			self.report("G11", True, f"{free >> 30} GB free, release image {image >> 20} MB, database up")


def load_facts(directory):
	def read(name):
		try:
			with open(os.path.join(directory, name)) as source:
				return source.read()
		except OSError:
			return ""

	def as_json(name):
		try:
			return json.loads(read(name))
		except ValueError:
			return None

	def as_int(name):
		text = read(name).strip()
		return int(text) if text.isdigit() else None

	def sha(path):
		try:
			with open(os.path.join(REPO, path), "rb") as source:
				return hashlib.sha256(source.read()).hexdigest()
		except OSError:
			return ""

	tables = {}
	for row in read("tables").splitlines():
		cells = row.split("\t")
		if len(cells) >= 5:
			tables[cells[0]] = {
				"bytes": int(cells[1]) if cells[1].isdigit() else 0,
				"rows": int(cells[2]) if cells[2].isdigit() else 0,
				"row_format": cells[3],
				"engine": cells[4],
			}
	return {
		"deployed": as_json("deployed"),
		"patch_log": [line.strip() for line in read("patches").splitlines() if line.strip()],
		"tables": tables,
		"site_apps": [line.split()[0] for line in read("apps").splitlines() if line.split()],
		"app_heads": as_json("heads") or {},
		"apps_json_sha": sha("apps.json"),
		"site_config_sha": sha("site-config.json"),
		"free_bytes": as_int("free"),
		"image_bytes": as_int("image"),
		"db_alive": read("db").strip() == "1",
		"lean": read("lean").strip() == "1",
	}


def main():
	parser = argparse.ArgumentParser(
		description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
	)
	parser.add_argument("--facts", required=True, help="directory written by ./deploy (preflight_facts)")
	args = parser.parse_args()
	code = Gate(load_facts(args.facts)).run()
	print()
	print(
		"Online-safe: this release can go out with ./deploy live."
		if code == 0
		else "Refused: deploy this release with ./deploy build, in a window."
	)
	return code


if __name__ == "__main__":
	sys.exit(main())
