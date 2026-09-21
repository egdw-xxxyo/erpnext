---
name: frappe-insights
description: "Frappe Insights BI app in this deployment: ./insights install/uninstall, deploy integration, apps.txt and asset-sync constraints, worker sync, translations. Use when working on Insights."
---

## Frappe Insights (BI Tool)

### Overview

Frappe Insights is an open-source BI tool installed as an additional Frappe app in the existing ERPNext bench. It runs inside the same containers — no separate deployment needed.

- **Source**: https://github.com/frappe/insights (branch `version-3` for Frappe v15)
- **Local clone**: `~/git/insights/` (for reference only, not used at runtime)
- **Access**: http://localhost:8080/insights (same host as ERPNext)
- **Credentials**: same as ERPNext (Administrator / admin, or any ERPNext user with Insights roles)

### Enabling/Disabling

Controlled by `insights_enabled` in `site-config.json`:

```json
{
  "server_script_enabled": 1,
  "insights_enabled": 1
}
```

- Set to `1`: `./deploy start`, `./deploy build`, `./deploy migrate` will auto-install Insights
- Set to `0` or remove: Insights is skipped (but not uninstalled if already present)
- Manual install/uninstall: `./insights install` / `./insights uninstall`

### How it works

The `./insights` script handles installation into the running ERPNext containers:

1. **`bench get-app insights`** on the backend container (clones from GitHub)
2. **`bench build`** (full rebuild of all apps — partial build corrupts `assets.json` hashes)
3. **`bench install-app insights`** on the site
4. **Syncs app code** to worker containers (queue-short, queue-long, scheduler) via tar pipe
5. **Copies built assets** to the frontend (nginx) container — required because nginx has a separate overlay mount for `sites/assets/` and can't see symlinks to backend's `apps/` directory

### How the deploy integration works

The `./deploy` script calls `./insights auto` twice during `start`, `build`, and `migrate`:

1. **Before restart**: syncs insights app code + assets to all containers
2. **Removes `insights` from `apps.txt`** right before `dc restart` — prevents workers from trying to import insights before files are synced
3. **After restart**: `./insights auto` runs again, re-syncs files (restart wipes non-persistent data), re-adds `insights` to `apps.txt`

This ordering is critical — if `insights` is in `apps.txt` when a worker starts but the module isn't synced yet, it causes `ModuleNotFoundError` spam in logs.

### Key architecture constraints

| Issue | Cause | Solution |
|---|---|---|
| `apps.txt` loses insights on restart | `configurator` service runs `ls -1 apps > sites/apps.txt` on every `dc up`, only sees frappe+erpnext from the Docker image | `./insights auto` re-adds `insights` to `apps.txt` after every restart |
| `ModuleNotFoundError` spam on scheduler/workers | Workers start and read `apps.txt` (has `insights`) before `./insights auto` syncs the module | `deploy` removes `insights` from `apps.txt` before restart, re-adds after sync |
| Frontend 404 on insights assets | nginx container has separate overlay mount for `sites/assets/`; symlinks to `apps/insights/...` are broken there | `fix_assets()` copies real files via `tar -ch` (follow symlinks) from backend to frontend container |
| Frontend 404 on frappe/erpnext CSS/JS after install | `bench build` regenerates `assets.json` with new hashes; frontend container still has old files from Docker image | `fix_assets()` copies ALL app assets (frappe, erpnext, insights) to frontend, not just insights |
| `bench build --app insights` corrupts asset hashes | Partial build regenerates `assets.json` with new hashes for ALL apps but only rebuilds insights bundles | Always do full `bench build` (no `--app` flag) when insights is present |
| `mysqlclient` fails to install | Insights depends on `ibis-framework[mysql]` which needs `pkg-config` + `libmariadb-dev` | `ensure_build_deps()` installs them via `apt-get` on all containers before `bench get-app` |
| Workers crash / can't import insights | Worker containers don't share app code filesystem with backend; files lost on every restart | `ensure_workers()` checks `import insights`, syncs via tar pipe + `pip install -e` if missing |
| `pip install -q` silently fails | Quiet mode hides build errors (e.g. missing `pkg-config`) | Always use `pip install -e` (no `-q`) and show tail of output |
| "Skipping fixture syncing" warnings during migrate | Frappe tries to sync insights fixtures during `bench migrate` — harmless, fixtures already exist from initial install | Safe to ignore; does not affect functionality |
| Old error logs persist in `docker-compose logs` | Docker accumulates logs across container restarts | `./deploy start --logs` uses `--since 0s` to only show new logs |
| `ModuleNotFoundError: No module named 'insights'` after uninstall | `bench uninstall-app` doesn't fully clean up: `tabDefaultValue.installed_apps` still lists insights, `tabDocType` records with `module=Insights` remain, `tabModule Def` "Insights" remains | `./insights uninstall` now does full DB cleanup via SQL: removes from DefaultValue, drops all Insights tables/DocTypes/Module Def/Roles |

### Build dependencies

Insights requires build deps not in the stock ERPNext image:
- `pkg-config`, `libmariadb-dev`, `gcc` (for `mysqlclient` / `ibis-framework`)
- Installed automatically by `./insights install` on all containers (backend + workers)
- **Not persistent** — lost on container restart/recreation, reinstalled automatically by `ensure_build_deps()`

### Data Sources

- A "Site DB" data source is auto-created on install, connecting to the ERPNext MariaDB
- Users need **Insights Admin** or **Insights User** role to see data sources
- Assign roles at: ERPNext → Setup → User → Roles

### Translation

Ukrainian translations are **hardcoded directly** in the Vue components in the forked repo (`egdw-xxxyo/insights.git`, branch `version-3`). The active frontend is `frontend/src2/` (NOT `src/`). The Frappe PO/MO translation system does NOT work reliably for Insights because:
- The v3 frontend (`src2/`) had no `__()` calls — strings were plain English
- Even with `__()`, translations load async and the app renders before they arrive
- `index.html` loads `src2/main.ts`, not `src/main.js` (confusing naming: `src2/` is v3, `src/` is v2)

To add/modify translations: edit the Ukrainian strings directly in `frontend/src2/*.vue` files in the fork repo, commit, push, then `./deploy start` will pull and rebuild.

### Files

| File | Purpose |
|---|---|
| `./insights` | Install/uninstall script |
| `./site-config.json` | Contains `insights_enabled` flag |
| `./deploy` | Calls `./insights auto` in `start`, `build`, `migrate` commands |
