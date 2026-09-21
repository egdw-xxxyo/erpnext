# Near-zero-downtime midday deploy (`./deploy live`)

## Context

Every release goes out through `./deploy build`, which takes the site down for minutes, forcing deploys into
off-hours. Goal: a separate deploy path runnable at midday. A few seconds of slower requests is acceptable;
**no 502s, no broken-asset pages, no forced reload or logout**.

Fixed constraints: single host, plain `docker compose`, no external load balancer, no second host. The
deliverable is a **new command** plus a new ops-dashboard action. `./deploy build` stays exactly as it is, as
the windowed path for releases the safety gate rejects.

### Where today's downtime comes from

`run_deploy` (`deploy:565-664`), in order:

- `dc up -d` (`deploy:577`) recreates **every** service with no ordering and no health gate — including
  `frontend`, which owns the only host `:8080` listener (3-8 s connection-refused) and `backend` (20-60 s of
  502s while gunicorn `--preload`-imports frappe/erpnext/hrms/frappe_whatsapp).
- `dc stop scheduler queue-short queue-long websocket` (`deploy:600`) — realtime dead for the whole migrate.
- `bench migrate` (`deploy:606`) bare, against a live-serving backend.
- `dc restart frontend` (`deploy:626`) — the listener outage, a second time.
- `fix_assets` (`deploy:306-311`) `rm -rf`s the asset tree nginx is serving from.
- `ensure_assets_manifest` (`deploy:278-282`) may run a multi-minute `bench build` inside the live backend.

Maintenance mode is never set, so users get 502s and MIME-type errors rather than a page. **Net: 1-5 minutes of
error pages, worst case 10+, plus in-flight requests SIGKILLed at 10 s.**

### The two discoveries that shape the design

**1. Assets are baked into the image and symlinked per-container, not shared.** The image ENTRYPOINT is
upstream frappe_docker's `main-entrypoint.sh` (verified via `docker history --no-trunc`):

```
rm -rf /home/frappe/frappe-bench/sites/assets
ln -s  /home/frappe/frappe-bench/assets  /home/frappe/frappe-bench/sites/assets
exec "$@"
```

So `sites/assets` is a **per-container window into that container's own image layer**, recreated on every
container start in every service (`frontend` included — its `command: nginx-entrypoint.sh` overrides CMD only).
nginx serves `/assets` with `root /home/frappe/frappe-bench/sites` + `try_files $uri =404`, so **the frontend
container's image is the asset origin.**

That makes naive blue/green impossible: swap `backend` to green and the new `assets.json` names hashed bundles
the blue frontend has never heard of — every `<script>`/`<link>` 404s. Swap the frontend too and you restart
the only `:8080` listener *and* destroy the old hashes open tabs still lazy-load.

The baked tree is **33 MB** and fully content-hashed (`"billing.bundle.js":
"/assets/frappe/dist/js/billing.bundle.WUY3N4ZW.js"`), so unioning several releases in one real directory is
cheap and collision-free. Only `assets.json` / `assets-rtl.json` are mutable.

**Load-bearing decision: de-couple asset serving from the image.** `sites/assets` becomes one real, additive,
content-hash-keyed directory in the shared `sites` volume holding the union of the last N releases. Every
container then serves an identical `/assets` tree regardless of image, and the cutover is a single atomic
rename.

**Corollary: `frontend` is infrastructure, not release payload.** Once assets come from the volume and the
nginx config from a bind mount, the frontend image is irrelevant to correctness. It gets its own
`${ERPNEXT_IMAGE_FRONTEND}` that the live path never touches, so it is never recreated and `:8080` never
disappears.

**2. nginx is fully overridable without touching the image.** Its entrypoint envsubsts
`/templates/nginx/frappe.conf.template` (confirmed present in the image) and substitutes **only** the vars in
its explicit list, so a bind-mounted template can introduce nginx runtime variables safely. nginx is 1.22.1,
built `--with-http_stub_status_module`.

---

## Phase A — cut most of the downtime, low risk, benefits `./deploy build` too

### A1. Per-release image tags

`deploy:7-8` hardcodes one fixed tag, repeated 7 more times in `docker-compose.yml` (`:5, :22, :51, :106,
:132, :151, :188, :202`). Every build overwrites the same tag, so two releases can never coexist and rollback
depends on old layers happening to survive — which `space-hard-clean` explicitly destroys (`deploy:858`).

**Where the value lives: `$DIR/.env`.** Compose auto-loads `<project directory>/.env`, and the project
directory is the directory of the first `-f` path — absolute in both wrappers (`deploy:102-108` `dc()` and
`ops/app/stats.py:68`, `:269`). One file serves `./deploy`, a bare `docker compose` run by an operator, and the
ops stats collector, with **no change to `dc()` and no `--env-file`** (a missing `--env-file` is a hard error in
compose 2.40; auto-load tolerates absence). Every service keeps a `:-` default so a host with no `.env` starts
exactly as before.

`.env` is per-host state like `.deploy-env` and must be gitignored (add after `.gitignore:28`).

```
ERPNEXT_IMAGE_BLUE=erpnext-uk:v16.31.1-v2026.09.18
ERPNEXT_IMAGE_GREEN=erpnext-uk:v16.31.1-v2026.09.15
ERPNEXT_IMAGE_FRONTEND=erpnext-uk:v16.31.1-v2026.09.15
ERPNEXT_ACTIVE_COLOR=blue
ERPNEXT_PREV_IMAGE=erpnext-uk:v16.31.1-v2026.09.15
```

`ERPNEXT_VERSION` at `deploy:7` is **also** the base-image build arg (`Dockerfile.full:2-3`). Do not conflate
the two:

```bash
ERPNEXT_VERSION="v16.31.1"
IMAGE_REPO="erpnext-uk"
IMAGE_NAME="$IMAGE_REPO:$ERPNEXT_VERSION"          # moving tag, every existing path still uses it
release_tag() { git -C "$DIR" describe --tags --always --dirty 2>/dev/null | tr -c 'A-Za-z0-9._-' '-'; }
RELEASE_TAG="$(release_tag)"
RELEASE_IMAGE="$IMAGE_REPO:${ERPNEXT_VERSION}-${RELEASE_TAG}"
ENV_FILE="$DIR/.env"
```

Helpers next to `dc()`: `env_set` (temp-file + rename upsert, no duplicates, never partial), `env_get`, and
`env_ensure` (seeds every key from `$IMAGE_NAME` + `blue`). `env_ensure` is called once at the top of the
`case` dispatch so `init`/`start`/`build`/`stop` behave identically on a host that has never seen `.env`.

`build_image` (`deploy:190-215`) tags both names in one `docker build`
(`-t "$RELEASE_IMAGE" -t "$IMAGE_NAME"`) and passes `--build-arg RELEASE_TAG`. `Dockerfile.full` gains, after
line 93:

```dockerfile
ARG RELEASE_TAG=unknown
ENV ERPNEXT_RELEASE=${RELEASE_TAG}
```

Use a top-level `x-images` anchor block so there is one source of truth per colour rather than eight copies,
with `blue: &image_blue ${ERPNEXT_IMAGE_BLUE:-erpnext-uk:v16.31.1}` and a separate
`frontend: &image_frontend ${ERPNEXT_IMAGE_FRONTEND:-${ERPNEXT_IMAGE_BLUE:-...}}`.

**Retention: keep 3 tags** (active, previous, previous-1). The image is 6.7 GB but layers are shared; the
per-release delta is only the layers after the cache break — `COPY erpnext/` (`Dockerfile.full:17`),
`COPY frappe/` (`:20-22`), the two `pip install -e` layers (`:51-52`), the extra-apps clone (`:74-81`,
cache-busted by `APPS_CACHE_BUST` whenever any fork moves) and `bench build --force` (`:93`). Expect
**~1.5-2.5 GB per retained tag**, so ~3-5 GB over the base. Prod is a 58 GB disk that has filled before —
measure the real delta on the first run and record it.

`build_image`'s existing `docker image prune -f --filter dangling=true` stays: both tags are applied in the
same `docker build`, so a release image is never dangling. But `space-hard-clean`'s
`docker image prune -a -f` (`deploy:858`) **must go** — it is the line that destroys the rollback image.
Replace with a selective `image_gc` keeping the newest N `erpnext-uk` tags, anything pinned in `.env`, and
anything any existing (even stopped) container references.

`ops/app/commands.py:117-131`'s `space-hard-clean` description is then a lie — it promises rollback is no
longer possible. Rewrite it in the same commit.

### A2. Never restarting nginx again

`deploy:626`'s `dc restart frontend` goes away permanently. Its comment (`deploy:621-625`) is right about why
it exists and wrong about the cheapest fix. **All three candidate mechanisms are used, each for a different
job:**

| Mechanism | Role |
|---|---|
| Bind-mount our own template | **Prerequisite.** The config is generated at container start from `/templates/nginx/frappe.conf.template`; changing it otherwise means rebuilding and therefore recreating the frontend. The entrypoint's envsubst list is fixed, so any nginx runtime variable we add survives untouched. |
| `resolver` + variable `proxy_pass` | **The permanent fix for `deploy:626`.** Upstream names re-resolve per request, so any container IP change self-heals in ≤10 s with no human action — including when a deploy crashes half-way, which is exactly when nobody is around to run a reload. |
| `nginx -s reload` | **The blue/green cutover primitive.** A reload never closes the listening socket: the master keeps `:8080`, new workers take the new config, old workers finish their in-flight requests and exit. Deterministic, instantaneous, zero refused connections, and it never serves two code versions at once. |

**Rejected: shared network alias alone.** With `backend` resolving to blue+green, DNS round-robin sends ~50% of
traffic to green the instant it starts — before gunicorn has finished importing frappe — and nginx will not
retry a POST (`non_idempotent` is off by default). You cannot health-gate before joining an alias, because a
container joins its aliases at creation. `docker network connect --alias` on a second network works around
that, but then draining blue requires `docker network disconnect`, which severs blue's DB and Redis
connections mid-transaction. Reload-based cutover has none of these problems.

**Files:**
- `.docker/nginx/frappe.conf.template` (new, committed) — bind-mounted over
  `/templates/nginx/frappe.conf.template`. Seed from `.docker/resources/core/nginx/nginx-template.conf`, which
  is an unused upstream copy; delete that in a separate commit so there is only one.
- `.docker/nginx/target/target.conf` (generated, gitignored) — bind-mounted read-only at
  `/etc/nginx/frappe-target/`, two `map` directives naming the live colour. Owned by `deploy`.

Template changes — drop both `upstream` blocks, then:

```nginx
# conf.d/*.conf is included inside http{}, so resolver/map/include are legal here.
# ipv6=off is required: docker's resolver returns an empty AAAA reply and nginx
# 1.22.1 logs an error for every lookup otherwise.
resolver 127.0.0.11 valid=10s ipv6=off;
resolver_timeout 5s;

# Exact filename, not a wildcard: a missing file must fail `nginx -t` loudly
# rather than leave $frappe_backend undefined at request time.
include /etc/nginx/frappe-target/target.conf;
#   map $host $frappe_backend  { default "backend:8000"; }
#   map $host $frappe_socketio { default "websocket:9000"; }

location = /nginx_status { stub_status; allow 127.0.0.1; deny all; }

location /socket.io {
	...
	proxy_redirect off;
	proxy_pass http://$frappe_socketio;
}

location @webserver {
	...
	proxy_redirect off;
	proxy_next_upstream error timeout;      # backstop only; never non_idempotent
	proxy_next_upstream_tries 2;
	proxy_connect_timeout 2s;
	proxy_pass http://$frappe_backend;
}
```

Two details that are easy to get wrong:

1. **URI semantics are unchanged.** nginx's rule: *if `proxy_pass` is specified without a URI, the request URI
   is passed to the server in the same form as sent by a client.* Both the old `http://backend-server` and the
   new `http://$frappe_backend` have **no URI component**, so they take the identical branch. Appending a path
   — even a bare `/` — switches to the "replace the part matching the location" branch and breaks every
   `/socket.io/*` path. Comment this in the template so a future edit does not do it.
2. **`proxy_redirect`.** `@webserver` was already safe (`proxy_redirect off`). `/socket.io` was not — it
   inherited the implicit `proxy_redirect default`, which is a **config-parse error** alongside a variable
   `proxy_pass`. Without the added line the frontend fails to start on the very first deploy of this change.
   This is the single highest-risk line in the plan; `nginx -t` in a throwaway container is its pre-flight.

Not a regression: the old `upstream` blocks had no `keepalive`, and `proxy_http_version 1.1` without
`proxy_set_header Connection ""` means there was no upstream keepalive to lose. `fail_timeout=0` is moot with
a single-address group.

Frontend service: `image: *image_frontend`, `restart: unless-stopped`, the two mounts, a `/nginx_status`
healthcheck, and **`depends_on: websocket` removed** — with the resolver, nginx no longer needs websocket to
exist at its own start, and the dependency means a swap of websocket could drag the frontend with it.

deploy-side helpers: `nginx_target_write` (write temp + `mv -f`, so a reader sees either the old file or the
new one), `nginx_target_ensure` (called near `env_ensure`, so no path can start a frontend whose `include`
points at nothing), `nginx_reload` (`nginx -t` then `nginx -s reload`, never `dc restart`), and
`nginx_wait_old_workers` (poll for `worker process is shutting down`, ≤45 s — old workers linger until their
connections close, `keepalive_timeout 15`).

`run_deploy:621-626` becomes: reset the colour pointer to blue, reload, stop the green colour, `env_set`.
**Invariant: `./deploy build` always ends with blue live and green stopped; `./deploy live` always ends with the
other colour live.** No ambiguity about which container serves.

### A3. Additive, atomically-published assets

**Wiring: bake the publisher into `Dockerfile.full`**, not a compose `entrypoint:` override. It must behave
identically in blue, green, frontend, workers, the one-shots *and* the throwaway migrator; a compose override
would need re-chaining to CMD in eight places and a host-side file present for every colour. Baking pins the
behaviour to the image that carries the assets.

```dockerfile
COPY .docker/assets/publish-assets-entrypoint.sh /usr/local/bin/publish-assets-entrypoint.sh
COPY .docker/assets/publish_assets.py            /usr/local/bin/publish_assets.py
ENTRYPOINT ["/usr/local/bin/publish-assets-entrypoint.sh"]
```

The entrypoint removes upstream's symlink if present (removing a symlink never touches its target), `mkdir -p`s
the real directory, runs `publish_assets.py`, then `exec "$@"`.

`publish_assets.py` (~60 lines):

- Walk the baked tree, skipping `assets.json` / `assets-rtl.json`.
- **Hashed files** (path contains `/dist/`): if the destination exists, **skip**. Content-hashed names never
  collide across releases, so older bundles survive and an already-loaded tab keeps resolving its own hashes.
- **Unhashed files** (`css/`, `js/`, `locale/`, and each app's non-`dist` subtrees — `images`, `icons`,
  `node_modules`): last-writer-wins via `dest.tmp.<pid>` + `os.replace`, same filesystem, so no reader ever
  sees a truncated file. Note `assets/css/` is also written at runtime by Website Theme generation
  (`/assets/css/standard_style.css`); under the symlink scheme that landed in an ephemeral layer and was
  regenerated per container — under a real volume dir it becomes persistent and shared, which is a bonus fix.
- Write `.releases/<RELEASE>.json` = the release's file list plus verbatim copies of its two manifests. This is
  what lets `deploy` publish the manifest at the cutover instant from a known-good source, lets rollback
  re-publish the previous release's manifest, and gives GC an exact keep-set.
- **Fast path**: if `.releases/<RELEASE>.json` exists and every listed file is present, return immediately — a
  blue/green restart, a worker recreate and a rollback become free instead of re-copying 33 MB.
- Runs as `frappe` (the image's `USER`), which owns the volume — no root, no `chown -R` (which `deploy:238`
  needed and which goes away with `sync_built_assets`).

**Blocker that must be handled: `bench build` compatibility.** `frappe/frappe/build.py:169-199`
`symlink(..., overwrite=True)` raises `IsADirectoryError: Cannot symlink over existing directory` (`:198`) when
the link name is a real directory, and `generate_assets_map()` (`:322-354`) points `apps/{app}/public` →
`sites/assets/{app}`. So under the real-dir scheme **`bench build` and the asset-linking side of
`bench install-app` fail.** For the live path that is desirable — but it must fail at pre-flight, not at
runtime. For the windowed path it would break `install_extra_apps` → `ensure_extra_apps` → `bench install-app`.

Fork change in our `frappe` submodule, opt-in so upstream behaviour stays the default:

```python
# frappe/frappe/build.py, in symlink()
if os.environ.get("FRAPPE_ASSETS_ADDITIVE") == "1" and os.path.isdir(link_name) \
        and not os.path.islink(link_name):
    _publish_additively(target, link_name)
    return
```

with `FRAPPE_ASSETS_ADDITIVE: "1"` on the erpnext services. `Dockerfile.full:93`'s `bench build --force` runs
at image-build time with no volume mounted and is unaffected either way.

**Publication order at the cutover.** The manifest is the only mutable file and the only thing that flips; the
bundles are already in the volume (published by green's entrypoint at container start), so this is a rename,
not a copy: read `.releases/<tag>.json`, write `.assets.json.new`, `os.replace`, then
`frappe.cache.delete_value("assets_json", shared=True)` (the one good line in the old `fix_assets`, at
`deploy:317-320`). Both colours share `redis-cache`, so one targeted delete is enough.

**Ordering is safe in both directions**, which is what additivity buys: manifest first and blue renders new
hashed URLs — they exist; code first and green renders old hashed URLs — they also exist. Flip the manifest
immediately before `nginx_reload` so the Redis flush has propagated by the time green takes traffic.

**Retention: keep 5 releases** (~165 MB). Generous because it is cheap, and 5 covers a tab left open across a
week of deploys plus two rollback hops. `./deploy assets-gc [--keep=5]` keys off **`assets.json`
reachability, never mtime**: keep-set = every hashed path in the newest N `.releases/*.json` manifests plus the
currently-published pair; delete only files under `*/dist/*` outside it; **never** delete unhashed files, which
have no versioning. **Runs at the START of `live`/`build`, never at the end** — the outgoing release's bundles
must survive for rollback. Wired into `space-clean`.

`ensure_assets_manifest`'s intent moves to a pre-flight against the *image*, in a throwaway container: if the
image's own `assets.json` names bundles the image did not emit, the release is broken and must not reach the
site. `bench build` in a live backend is never the answer, and under the additive scheme it cannot even run.

### A4. Health gate, real restart policy, drain window

Verified from the image's `start.sh`: `--timeout=120`, `--workers=2`, `--threads=4`,
`--worker-class=gthread`, `--preload`, and **no `--graceful-timeout`** → gunicorn's default 30 s.
`docker-compose.yml` sets **no `stop_grace_period` anywhere** → compose's default 10 s → SIGTERM then SIGKILL
at 10 s. So today, on every deploy, blue's in-flight requests are killed mid-response and rq workers die
mid-job.

- `backend`: `restart: unless-stopped`, `stop_grace_period: 30s`, healthcheck on
  `/api/method/ping`, and an **explicit gunicorn `command`** adding `--graceful-timeout=25` (the image's
  `start.sh` exposes `GUNICORN_{THREADS,WORKERS,TIMEOUT}` but not the graceful timeout, and the drain protocol
  needs it). Exec form, so gunicorn is PID 1 and SIGTERM reaches it directly.
- `queue-long` / `queue-short` / `scheduler`: `stop_grace_period: 300s` — `bench worker` treats SIGTERM as a
  warm shutdown (finish the current job, then exit), and 10 s SIGKILLs long jobs mid-transaction today.
- `websocket`: `stop_grace_period: 15s`.
- `configurator` / `create-site`: `restart: "no"` — one-shots; the `deploy:` block being replaced is Swarm-only
  and was silently ignored.

**Readiness probe.** `frappe.ping` is `@whitelist(allow_guest=True)` returning `"pong"`
(`frappe/frappe/__init__.py:1553-1555`), routed at `frappe/frappe/api/v2.py:278`. A 200 proves the image
imported, gunicorn is listening, the DB is reachable, the site resolves and the session/Redis path works. Site
resolution normally comes from nginx (`FRAPPE_SITE_NAME_HEADER: frontend`), so the probe must send
`-H 'Host: frontend'`.

`backend_ready` requires **3 consecutive 200s** so one lucky answer during worker boot cannot pass the gate.
`--preload` means a green container that is up has already imported the new code — an import error kills it at
start, so "it answered" is a strong statement. `backend_warm` then primes both workers (2 × 4 gthreads = 8
concurrent) with ~24 pings plus one `/app` before they see real traffic.

`wait_for_backend` (`deploy:178-188`) is **defined, never called, and wrong** — `bench doctor | grep OK` and
`python3 -c "import frappe"` say nothing about whether gunicorn is accepting on `:8000`. Replace its body with
`backend_ready` and **call it** after every `dc up -d`.

**Why a 25 s graceful bound rather than 120 s.** At the moment blue is signalled,
`nginx_wait_old_workers` has already confirmed every nginx worker holding the old config is gone. The only
requests still on blue began *before* the reload and are still running — i.e. reports that already exceeded
~20 s. Those get 25 more seconds. A report that has run 45 s and then dies is one user seeing one slow request
fail, which is inside the stated tolerance. Waiting 120 s on every deploy to protect the tail of the tail is
not worth it. `PROXY_READ_TIMEOUT: 120` stays as-is: it bounds normal operation, not the drain.

### A5. `setup_custom_fields` must fail loudly, and stop stampeding the cache

`deploy:632-637` treats a failure as non-fatal, so a release can ship with **none** of its custom fields —
silently, if `--silent` routed stderr away. This has already happened: see the `v2026.09.18` release note about
a Quotation Approval Workflow throw swallowing every later setting in the release. Make it fatal on both paths;
on the live path it aborts **before the swap**, which is the cheapest place to abort.

The 3347-line module also calls **`frappe.clear_cache()` 13 times** globally (68 setup functions, 38
`_create_custom_fields()` calls, ~190 field dicts). Each is a full flush of bootinfo, doctype meta and
`assets_json` — thirteen cache-rebuild stampedes while blue serves real users. Not errors, but well past
"seconds of slow". Add an `execute_quiet()` entry point used only by the live path, which monkeypatches
`frappe.clear_cache` to drop only the **argument-less** global form (scoped `clear_cache(doctype=...)` /
`(user=...)` calls keep working) and flushes once at the end.

Before merging, `grep -n 'frappe.clear_cache(' erpnext/patches/setup_custom_fields.py` and check all 13 sites:
if any relies on a global flush for correctness, narrow that call site first.

### A6. The rest of Phase A

- `run_deploy`'s `dc up -d` → `dc up -d --no-deps` for only the services whose image changed, so `db`,
  `redis-*` and `frontend` are never recreated.
- Worker stop → `-t 300`; **`websocket` dropped from the stop list** (it is node/socketio and holds no
  `tabDocType` metadata handle of its own — stopping it drops every realtime connection for the whole migrate
  window for no benefit).
- Delete `sync_built_assets` (dead code), `ensure_assets_manifest` (obsolete) and `fix_assets`' `rm -rf`
  (harmful); repoint `./deploy fix-assets` at non-destructive re-publication.
- `strip_extra_apps`' `redis-cli FLUSHALL` (`deploy:535`) → targeted `frappe.clear_cache()` +
  `delete_value("assets_json", shared=True)`. `FLUSHALL` does not log anyone out (sessions are authoritative
  in `tabSessions`) but it nukes every user's bootinfo and meta cache at once.
- `ops/app/stats.py:68`, `:269` — add the green overlay to the `DC=` string it builds, or the dashboard's
  containers panel will omit the colour actually serving traffic.

**Remaining downtime after A:** frontend never recreated, nginx never restarted → listener outage and asset-404
window are **0 s**. The backend is still recreated in place, so **~20-60 s of 502s** — measure it, it is the
number Phase B removes. Migrate runs with workers down: no user-visible error, jobs queued.
**~20-60 s, down from 1-5 min.**

---

## Phase B — blue/green swap

### B1. Topology

A second compose file, **always passed by `dc()`**, so green services are declared (not "orphans"), visible to
`dc ps` and the ops containers panel, and gated behind a profile so `dc up -d` on the windowed path does not
start them.

`docker-compose.green.yml` declares `green_backend` and `green_websocket` using
`extends: {file: docker-compose.yml, service: backend|websocket}` — so volumes, environment and command have
exactly one definition — overriding only `image: ${ERPNEXT_IMAGE_GREEN:-...}`, `profiles: ["green"]`,
`restart: unless-stopped`, `stop_grace_period` and the healthcheck.

```bash
dc()  { docker compose -p docker -f "$DIR/docker-compose.yml" -f "$DIR/docker-compose.green.yml" "$@"; }
dcg() { COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}green" dc "$@"; }
```

Colours alternate: `active_color` reads `ERPNEXT_ACTIVE_COLOR` from `.env`, the deploy targets the other.
The inactive colour is **stopped, not removed** — `restart: unless-stopped` respects a manual stop (`always`
would fight us), its tag stays pinned in `.env`, so rollback is `dc start` of a container that already exists.

Workers get **no colour**. They serve no traffic; a gap is queued work in Redis, not an error page. They are
recreated with the new image after the swap.

### B2. The migrator container

`bench migrate` runs from the **new** image, in a throwaway container, while blue (old code) keeps serving:

```bash
docker run --rm --network docker_frappe_network \
  -v docker_sites:/home/frappe/frappe-bench/sites -v docker_logs:/home/frappe/frappe-bench/logs \
  -e DB_HOST=db -e DB_PORT=3306 -e FRAPPE_ASSETS_ADDITIVE=1 ... \
  --entrypoint /usr/local/bin/publish-assets-entrypoint.sh "$RELEASE_IMAGE" bash -lc "$CMD"
```

No `--network-alias`, so it is invisible under any name nginx resolves and cannot receive a request.
`docker compose run` is deliberately **not** used: it attaches with the service name as an alias, which would
put a migrating container into the `backend` DNS name. Keeping the publisher entrypoint means the migrator also
lands the new release's bundles before green even starts.

### B3. Cutover sequence (~3-6 s)

```bash
# 1. Green up. Blue untouched, still serving everything.
env_set ERPNEXT_IMAGE_GREEN "$RELEASE_IMAGE"
dcg up -d --no-deps green_backend green_websocket

# 2. Gate. Green is in no DNS name nginx knows, so this is free.
backend_ready "$GREEN_CID" || abort_before_swap "green never answered /api/method/ping"
backend_warm  "$GREEN_CID"

# 3. Publish the new manifest (atomic rename) + flush assets_json from Redis.
assets_publish_manifest "$RELEASE_TAG"

# 4. Cutover: atomic rename + reload. The :8080 listening socket is never
#    closed; old nginx workers finish in-flight requests against blue.
nginx_target_write "green_backend:8000" "green_websocket:9000"
nginx_reload || abort_after_swap "nginx -t rejected the green target"
env_set ERPNEXT_ACTIVE_COLOR green

# 5. Drain: every old nginx worker must exit before blue is signalled.
nginx_wait_old_workers

# 6. Blue down: SIGTERM -> gunicorn graceful 25s -> SIGKILL at 30s.
dc stop backend websocket

# 7. Workers onto the new image (jobs queued in Redis meanwhile).
env_set ERPNEXT_IMAGE_BLUE "$RELEASE_IMAGE"
dc up -d --no-deps queue-short queue-long scheduler
```

**Realtime**: socket.io connections on blue's websocket close when it stops; frappe's client reconnects
automatically to green. No page reload, no logout — sessions are authoritative in `tabSessions` and both
colours share `db` and `redis-cache`, so there is nothing to invalidate. This is exactly why
`strip_extra_apps`' `FLUSHALL` must never run on the live path.

`proxy_next_upstream` is only a backstop: with named colours `$frappe_backend` resolves to one address, so
there is no second address to retry to. It earns its place for a container that dies unexpectedly between two
resolver refreshes, where `error` + `proxy_connect_timeout 2s` turns a 502 into a 2 s retry. Deliberately no
`non_idempotent`: a POST is never replayed.

### B4. Full `./deploy live` order

1. `assets_gc --keep=5` (the outgoing release survives; the one before the previous goes).
2. **Pre-flight gate** (Phase C). Refuses → exit 3, nothing touched.
3. Quiesce workers with `dc stop -t 300 scheduler queue-short queue-long`.
4. **Expand**: `bench migrate` in the migrator container, behind the running release.
5. `setup_custom_fields` (via `execute_quiet`) in the same container, **fatal**.
6. Workers back up on the new image.
7. **Swap**: B3.
8. **Contract: nothing. Ever.** See below.

**Why keep quiescing the workers** (the brief asked for a justification): `deploy:596-600`'s comment is
correct — rq workers hold a metadata lock on `tabDocType` long enough to starve the `ALTER` in
`frappe.patches.v16_0.switch_default_sort_order` into a lock-wait timeout, which kills the migration. A stopped
worker is **not an outage**: jobs enqueued while it is down sit in `redis-queue` and run when it returns, and
no user sees an error page — which is the actual goal. Keeping workers alive through the migrate buys
queued-job latency we do not need and re-introduces the exact failure that line was added to fix. The only
change from today is the grace period. Blue's own gunicorn workers do hold short-lived metadata locks per
request, but requests are bounded at 120 s and the gate refuses any DDL that cannot tolerate a short wait.

**Contract steps never run on the live path.** No dropped columns or indexes, no renames, no whole-table
backfills — every one is a gate refusal. Contraction lands in the next `./deploy build`, in a window, where
`maintenance_mode` is acceptable. Stating this plainly is what makes expand-then-swap sound: at every instant
between the start of migrate and the end of the swap, **both** the old and the new code run correctly against
the database.

### B5. Abort and rollback

| Stage | State if we stop here | Action |
|---|---|---|
| Pre-flight | Nothing touched | `exit 3` with the failed checks |
| Assets published | New bundles in the volume, `assets.json` untouched | Nothing to undo; `assets_gc` reclaims later. Additivity makes a half-published release invisible |
| Workers stopped | Jobs queueing in Redis | `dc start` them and exit |
| **`bench migrate` failed mid-run** | DB partially migrated, old code still serving | **Do nothing to the DB.** `bench migrate` is not transactional across patches, so there is no unwind — but the gate guaranteed every change is additive, so old code keeps working. Restart workers on the old image, leave blue serving, report the failing patch. No rollback, no restore, no downtime |
| `setup_custom_fields` failed | Migrated DB, some fields missing, old code serving | Same; abort before the swap. This is why it is fatal here — the failure is cheap before the swap and expensive after |
| Green failed the health gate | Migrated DB, green unreachable, blue serving | `dcg stop`; workers back on the old image. Old tag + migrated schema is a fine end state, by the additive argument |
| After `nginx -s reload` | Green live | Not an abort — a rollback |

`./deploy rollback [--to <tag>]` is the same cutover in reverse, and fast because the outgoing colour's
container still exists (stopped, image pinned in `.env`, assets and `.releases/<tag>.json` already in the
volume): `dc start` it → `backend_ready` → `assets_publish_manifest <previous tag>` → `nginx_target_write` +
`nginx_reload` → `nginx_wait_old_workers` → stop the other colour → `env_set` → workers back.
**Expect 5-15 s, all of it health-gate and drain, zero of it downtime.** It refuses up front if the target
image is gone from the store, naming `space-hard-clean` as the cause.

**Covers:** application code, Python and JS, assets, nginx routing, the ops-visible version.

**Does not cover the database.** Schema changes stay applied. Rows written by the new code stay written. Patch
Log entries, new Custom Field rows, `after_migrate`'s Release Note upserts and `payroll_ua` property setters
all stay. There is no DB rollback in this design and there is not going to be one — a midday restore of a
2.7 GB backup is the thing being avoided.

**Why that is sufficient:** the gate refused, before anything ran, any change the *previous* release cannot
tolerate. So the previous release's code sees a schema that is a strict superset of what it knows, plus data it
ignores. **The gate and rollback-by-image are one mechanism, not two** — which is why the gate must land before
the command is exposed.

---

## Phase C — the pre-flight safety gate

`tools/deploy-preflight.py` (new), invoked as `./deploy live --check-only` (safe any time, its own
non-destructive ops action) and implicitly at the start of `./deploy live`. Exit 0 = online-safe; exit 3 =
"use the windowed deploy", with reasons. One PASS/REFUSE line per check, with the evidence.

Inputs: the deployed release, recorded by **both** `build` and `live` into `sites/.deployed-release.json` in the
volume — `{tag, erpnext_sha, frappe_sha, apps: {name: resolved_head}, at}` — and HEAD.

**"Online-safe" means additive-only in every dimension.** Every check **fails closed** and passes only on a
positive, mechanical proof.

| # | Check | Refuses when |
|---|---|---|
| G0 | Clean tree, HEAD tagged | `git status --porcelain` non-empty, or no tag on HEAD. Live deploys are releases, not working states |
| G1 | Deployed release known | `sites/.deployed-release.json` absent, or its `erpnext_sha` not an ancestor of HEAD. No diff → no proof → no live path |
| G2 | New patches explicitly marked | For each line added to `erpnext/patches.txt` or `frappe/frappe/patches.txt` since the deployed sha **and** absent from `tabPatch Log`: refuse unless the module defines `ONLINE_SAFE = True` with a one-line `ONLINE_SAFE_REASON`. **Default is unsafe** — no regex guessing at intent; an author who wants the live path says so, in the diff, where a reviewer sees it |
| G3 | Hard DDL/data rules, even for marked patches | `ast`-walk each new patch module and its string literals: refuse on `DROP TABLE\|COLUMN\|INDEX\|KEY`, `TRUNCATE`, `ALTER TABLE`, `RENAME`, `frappe.db.sql_ddl`, `frappe.rename_doc`, `frappe.db.change_column_type`, `frappe.db.delete(`, `frappe.delete_doc("DocType"\|"Custom Field")`; and on any `frappe.db.sql` / `frappe.qb.update` write with no `LIMIT` or batching. `ONLINE_SAFE` **cannot** override G3 |
| G4 | `pre_model_sync` additions | Any new line in the `pre_model_sync` half — those run before the schema is updated and are likelier to assume a shape. Conservative on purpose; all 3 new patches since `v2026.09.15` are post |
| G5 | DocType JSON diff is additive | Parse both sides of `git diff <deployed>..HEAD -- '*/doctype/*/*.json'` as JSON (a parser, not a regex, across all 753 files). Refuse on a removed field, changed `fieldname`, `fieldtype` change that is not a documented widening, changed Link `options`, newly-set `unique`/`set_only_once`, removed doctype, changed `autoname`/`istable`/`is_submittable`, removed Select option. Pass: new fields, new doctypes, labels, descriptions, permissions, appended Select options |
| G6 | App set unchanged | `apps.json` enabled set ≠ the site's `list-apps`; or any `apps.json` entry's `git ls-remote` HEAD differs from the recorded one (we cannot diff `hrms` / `frappe_whatsapp` / `insights` source, so an extra-app move is windowed by definition); or `apps.json` itself changed. This one rule also keeps `install_extra_apps`, `strip_extra_apps` and `./insights auto` off the live path entirely |
| G7 | New image's assets complete | The image's own `assets.json` names a bundle the image did not emit |
| G8 | Planned ALTERs are cheap | Collect new columns from G5's additions **and** from an `ast` diff of `setup_custom_fields.py` (collect `(doctype, fieldname)` pairs both sides and diff; ~41 new this release, hitting Item / Employee / Serial No / Sales Order / Quotation). For each target table read `DATA_LENGTH+INDEX_LENGTH` and `TABLE_ROWS` from `information_schema.TABLES`. **Pass** a nullable column appended to an InnoDB table that is not `ROW_FORMAT=COMPRESSED` and still has instant-column budget (`INNODB_SYS_TABLES`) — MariaDB 10.6 does that `ALGORITHM=INSTANT`, metadata-only, size-irrelevant. **Refuse** any new column not provably INSTANT on a table over 1 GiB, and **always** a new index on a table over the threshold (`ADD INDEX` is online in 10.6 but takes minutes and blocks concurrent DDL). Print the numbers: `tabItem 412 MB / 1.1M rows, 1 nullable column -> INSTANT, OK` |
| G9 | Hooks unchanged | `erpnext/hooks.py`'s `after_migrate` list (`:123-126`) differs, or a `before_migrate` appears. Today's two entries — `release_note.sync_release_notes` (78 upserts) and `payroll_ua.setup.setup_attendance_sheet` (`create_custom_fields` + `make_property_setter` on `tabAttendance`/`tabEmployee`) — are known and their ALTERs are covered by G8; a *new* entry is unreviewed arbitrary code |
| G10 | `site-config.json` unchanged | Differs from the deployed sha's. `apply_site_config` writes global config both colours read |
| G11 | Headroom | Free disk < new image size + 200 MB, or `db` unhealthy. A half-published asset tree or a full disk mid-migrate is the worst outcome available |

Calibration target: `erpnext/patches/v15_0/rework_opportunity_status.py` must be **refused** — it fails G3 three
times over (unbatched `update tabOpportunity` at `:57`, `frappe.qb.update` at `:58-63`, per-Kanban-board
`doc.save()` loop at `:93-112`). Correct outcome: that release was a windowed release. Historical shape to also
catch: `v16_0/drop_redundant_serial_no_index_from_sabb` (`DROP INDEX` on a large table).

This conservatism is the point. It is better for the gate to send a *safe* release down the windowed path than
to let one unsafe release through, because the gate is the entire reason rollback-by-image is sufficient.

**Degraded fallback, off the happy path.** For a release the gate rejects that must still ship midday:
`frappe/frappe/app.py:227-231` raises `SessionStopped` under `maintenance_mode` unless
`allow_reads_during_maintenance` is set, in which case `setup_read_only_mode()` (`:248-263`) keeps reads
working on a read-only transaction while the migration runs. Worth having eventually as
`./deploy build --read-only-window`. Not part of `live`.

---

## Ops dashboard wiring

`ops/app/commands.py` — three new `Command` entries, mirroring the `"build"` entry at `:66-82` (same
`&&`-gated backup via the `pre_deploy_backup` pref, same `--no-ops`, same fixed-argv discipline described at
`commands.py:1-7`):

- `live-check` — `./deploy live --check-only`, non-destructive.
- `live` — `destructive=True`, **`needs_clean_tree=True`** so the dashboard blocks it (`routes/actions.py:57-64`)
  before the host-side gate has to.
- `rollback` — `destructive=True`, description stating plainly that it does **not** roll back the database.

Also required or the entries are invisible / mis-rendered:

- `ops/templates/partials/actions.html:23` — the rendered key list is hardcoded
  (`['update-repo', 'backup', 'build', 'switch-branch', 'ops-rebuild']`). Add the three new keys.
- `ops/app/progress.py` — `LABELS` (`:31-48`) gains `preflight`, `assets-gc`, `publish-assets`, `green`,
  `swap`, `drain`, `workers`, `rollback`; `EXPECTED` (`:51-68`) gains `"live"` and `"rollback"` lists.

**Step names need no other registration.** `progress.parse` derives the order from the marker lines themselves
and falls back to the raw phase name (`progress.py:118`); `EXPECTED` only feeds the cosmetic "step N of M".
`jobs.py` is fully generic. So `ops_step` calls in the new `live)` case work with no ops change — `LABELS` /
`EXPECTED` just make them read nicely. `skip` is a supported status alongside `start|ok|fail`.

**Ordering override:** implement A → B → C, but **do not expose `live` in the dashboard until C exists.** Until
then it is CLI-only behind an explicit `--i-have-reviewed-the-diff` flag. Phase B without Phase C is a one-click
path for shipping `rework_opportunity_status.py`-shaped releases with no window, and the rollback story is only
sound *because* the gate ran. A button that looks safe and is not is worse than no button.

---

## Verification

Per CLAUDE.md the only deploy command Claude runs is `./deploy build --silent`. Everything below is for the
operator.

### Local Mac — prove the parts that fail structurally

Laptop timings are meaningless; these four checks are not.

1. **nginx config parses with the variable `proxy_pass`.** Highest-risk line in the plan — the implicit
   `proxy_redirect default` in `/socket.io` is a parse error alongside a variable `proxy_pass`, and the failure
   mode is "frontend will not start". Run the image's `nginx-entrypoint.sh` in a throwaway container with the
   template and target mounted and all eight envsubst vars set, then `nginx -t`.
2. **`.env` really is auto-loaded** from the compose file's directory, from a different cwd — the assumption the
   whole tag scheme rests on: `(cd / && docker compose -p docker -f ~/git/erpnext/docker-compose.yml -f
   ~/git/erpnext/docker-compose.green.yml config | grep -c 'erpnext-uk:v16.31.1-')`.
3. **`extends` produced a green service identical to blue** except `image`, `healthcheck`, `profiles`,
   `container_name` — diff the two service dicts out of `docker compose config`. Anything else differing is a
   bug.
4. **Assets are a real dir, unioned across two releases, only the manifest mutable** —
   `ls -ld sites/assets; ls sites/assets/.releases/; ls sites/assets/frappe/dist/js | wc -l`.
5. **The gate refuses a known-bad release**: `./deploy live --check-only` must exit 3 citing G3 on
   `rework_opportunity_status.py:57`.

### The continuous probe — `tools/deploy-probe.sh` (new)

"Zero error pages" has to be measured, not asserted. Four request classes, because they fail for different
reasons:

- `GET /api/method/ping` — backend reachable.
- **`POST /api/method/ping`** — proves no non-idempotent request is 502'd, the case `proxy_next_upstream`
  deliberately does not cover.
- **a hashed asset URL captured *before* the deploy starts** (read `desk.bundle.js` out of `assets.json` at
  startup) — proves an already-loaded tab keeps resolving its old hashes, i.e. the additivity claim.
- `GET /socket.io/?EIO=4&transport=polling` — proves the `/socket.io` variable `proxy_pass` +
  `proxy_redirect off` are right.

5 rounds a second, `--max-time 15`, counting non-200s as `bad` and >2000 ms as `slow`, printing each failure
with its code and latency.

**Acceptance: `bad=0`.** `slow>0` is expected and acceptable — that is the "seconds of slow" that was signed up
for. Also capture nginx's own 5xx/404 count either side of the deploy from
`/var/log/nginx/access.log`; it should not move.

### Dev (172.16.105.103), then prod (172.16.51.10)

1. Dev to Phase A; probe across a `./deploy build`. Expect `bad>0` still (the backend recreate window) —
   record the number; it is the Phase B target.
2. Phase B on dev. Probe **from a third machine**, not the host, so it traverses the real network path and the
   cloudflared ingress. Require `bad=0` across three consecutive `./deploy live` runs, **including one
   green→blue→green alternation** (proves the colour bookkeeping in `.env`, not just the happy direction).
3. `./deploy rollback` immediately after a successful live deploy, probe running. Require `bad=0` and confirm
   the previous release's hashed bundles still resolve.
4. **Negative tests on dev — the ones that matter.** A gate that has only ever said PASS has not been tested.
   - Synthesise unsafe releases (a patch with `DROP INDEX`, a doctype JSON with a removed field, a new
     `after_migrate` entry) and confirm each is refused with the right check id.
   - Kill the migrator mid-`bench migrate`; confirm the site keeps serving on the old tag with a partially
     migrated schema, `bad=0` throughout. This is the claim the abort story rests on.
   - Point `ERPNEXT_IMAGE_GREEN` at a deliberately broken image; confirm the abort leaves blue serving,
     `bad=0`.
5. Phase C on dev: run `live-check` against every tag since `v2026.09.15` and confirm each verdict matches a
   manual read of the diff — in particular that the `rework_opportunity_status.py` release is refused.
6. Prod: `./deploy backup --with-files` off-host, then `live-check`, then `live` with the probe running from a
   workstation, mid-morning rather than peak, with `./deploy rollback` ready. Only after that is it a midday
   routine.

---

## Bugs in the current script that work directly against this goal

| # | Bug | file:line | Phase |
|---|---|---|---|
| 1 | `wait_for_backend` is defined and **never called**; its logic (`bench doctor \| grep OK`, `import frappe`) proves nothing about gunicorn listening. The deploy has no HTTP health gate at any point | `deploy:178-188` | A |
| 2 | `deploy.restart_policy` is **Swarm-only syntax, silently ignored by compose** — 8 occurrences. Nothing restarts on failure today | `docker-compose.yml:7-9` + 7 more | A |
| 3 | No `stop_grace_period` anywhere → compose's 10 s default SIGKILLs gunicorn mid-response and rq workers mid-job on **every** deploy. Gunicorn's own `--graceful-timeout` is unset (default 30 s) and unreachable behind the 10 s kill | `docker-compose.yml` (all services), image `start.sh` | A |
| 4 | `setup_custom_fields` is **non-fatal** — a release can ship with none of its custom fields, silently under `--silent` | `deploy:632-637` | A (loud fatal) / B (abort before swap) |
| 5 | `fix_assets`' `rm -rf` runs in the frontend container and **follows the symlink into that image's own baked asset dirs**, deleting them, then tars them back from a container running the same image. Self-inflicted `/assets` 404 window for zero gain, up to 3× | `deploy:306-311` | A (delete) |
| 6 | `sync_built_assets` is **dead code**: its `--entrypoint test` guard bypasses the entrypoint that creates the symlink, so the path never exists and it always short-circuits | `deploy:217-241` | A (delete) |
| 7 | `ensure_assets_manifest` can run a multi-minute `bench build` **in the live backend**; its comment at `:243-252` describes a pre-v16 world, and under the additive scheme the call would hard-fail at `frappe/frappe/build.py:198` | `deploy:253-285`, esp. `:278-282` | A (delete → image pre-flight) |
| 8 | `redis-cli FLUSHALL` on `redis-cache` nukes bootinfo, doctype meta and `assets_json` for every logged-in user mid-deploy | `deploy:535` | A (targeted); live path never calls it |
| 9 | `dc up -d` recreates **every** service — `db`, `redis-*`, and the frontend that owns the only `:8080` listener — with no ordering and no health gate | `deploy:577` | A (`--no-deps`, scoped) |
| 10 | `dc restart frontend` drops every in-flight request and removes the host `:8080` listener, to solve a problem `resolver` solves for free | `deploy:626` | A (delete) |
| 11 | `space-hard-clean`'s `docker image prune -a -f` destroys the previous release's image — the one thing rollback needs — and its dashboard description makes that a documented promise | `deploy:858`, `ops/app/commands.py:117-131` | A (`image_gc` + rewrite the text) |
| 12 | `./insights auto` can `dc restart queue-short queue-long scheduler` in the middle of a deploy | `insights:87-98` | A (windowed only; G6 keeps it off the live path) |
| 13 | `ops/app/stats.py` builds its own `DC=` string without the green overlay; left unchanged, the dashboard's containers panel omits the colour actually serving traffic | `stats.py:68`, `:269` | A (with the overlay) |

Items 1-3 are worth fixing first even if the whole live path were cancelled: they cost nothing, they are pure
bug fixes, and 2 and 3 mean the current windowed deploy kills in-flight requests and in-flight jobs on every
single run.

---

## Downtime after each phase

| | Remaining |
|---|---|
| Today | 1-5 min of error pages, worst case 10+; in-flight requests SIGKILLed at 10 s |
| After A | **~20-60 s** of 502s from the in-place backend recreate. Listener outage and asset-404 window are 0 s |
| After B | **0 refused connections, 0 502s, 0 asset 404s, no forced reload or logout.** Cost is latency: a few hundred ms on the first requests reaching green, <1 s while `assets_json` re-caches. Bounded exception, stated up front: a request that started on blue more than ~20 s before the cutover may be killed at gunicorn's 25 s graceful timeout — one user, one slow request |
| After C | Unchanged. C buys no seconds; it converts "this release was not online-safe" from a midday production discovery into a refusal with a reason |

---

## Critical files

- `deploy`
- `docker-compose.yml`, `docker-compose.green.yml` *(new)*
- `.docker/nginx/frappe.conf.template` *(new; seed from the unused `.docker/resources/core/nginx/nginx-template.conf`, then delete that)*
- `.docker/assets/publish_assets.py`, `.docker/assets/publish-assets-entrypoint.sh` *(new; wired in `Dockerfile.full`)*
- `frappe/frappe/build.py` *(submodule: `FRAPPE_ASSETS_ADDITIVE` branch in `symlink()` — commit and push the submodule before the erpnext pointer)*
- `erpnext/patches/setup_custom_fields.py` *(`execute_quiet()`)*
- `tools/deploy-preflight.py`, `tools/deploy-probe.sh` *(new)*
- `ops/app/commands.py`, `ops/app/progress.py`, `ops/app/stats.py`, `ops/templates/partials/actions.html`

## Release note

Append to `erpnext/release_notes/v2026.09.18.md` (the file for today's release already exists) in Ukrainian,
per the mandatory release-note rule.
