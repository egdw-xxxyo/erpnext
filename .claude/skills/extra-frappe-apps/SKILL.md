---
name: extra-frappe-apps
description: "apps.json extra Frappe apps (HRMS, CRM, WhatsApp fork): how they are built into the image, installed and uninstalled on deploy, and how to fork one. Use when adding, disabling or customising an app."
---

## Extra Frappe Apps (apps.json)

Extra apps (HRMS, CRM, ...) are configured in `apps.json` in the repo root. The file is **gitignored** (per-environment config, like `site-config.json`) — copy `apps.json.example` to `apps.json` on each machine. Docker build fails without it:

```json
[
  { "name": "hrms", "repo": "https://github.com/egdw-xxxyo/hrms.git", "branch": "version-15", "enabled": true },
  { "name": "crm", "repo": "https://github.com/frappe/crm.git", "branch": "v1.77.3", "enabled": true }
]
```

- **Build time**: `Dockerfile.full` clones ALL listed apps (enabled or not) into the image, pip-installs them, runs `yarn install` if the app has a `package.json`, and adds them to bench `apps.txt` so `bench build` compiles their assets. Disabled apps stay in the image so `bench uninstall-app` can run (it needs the app code).
- **Deploy time**: `./deploy` (`ensure_extra_apps`) installs every `enabled: true` app on the site and **uninstalls** any `enabled: false` app that is still installed. **Uninstall deletes all of that app's DocType data from the DB.**
- Asset sync (`sync_built_assets`, `fix_assets`) picks up enabled apps dynamically from `apps.json`.
- To add an app: add an entry, then `./deploy build --silent`. To disable: set `enabled: false`, rebuild (data loss warning above applies).
- To customize an app's code: fork it (convention: `egdw-xxxyo/<app>`), point `repo` at the fork. Changes must be pushed to the fork — the image clones from the remote, there is no local submodule for extra apps (only `frappe/` remains a submodule).
- The old `hrms_app/` submodule was removed; HRMS now comes via apps.json.
