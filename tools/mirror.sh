# Standby mirror, sourced by ./deploy. Main (MIRROR_ROLE=primary) keeps a
# binary log; the mirror (MIRROR_ROLE=replica) replicates main's site database
# over an SSH tunnel, pulls attachments, and can take over while main is
# unreachable. Only one side ever takes writes: failback copies the mirror's
# database and files back over main. Runbook: docs/mirror-standby.md.

MIRROR_ENV_FILE="$DIR/.mirror.env"
if [ -f "$MIRROR_ENV_FILE" ]; then
  set -a; . "$MIRROR_ENV_FILE"; set +a
fi
MIRROR_ROLE="${MIRROR_ROLE:-}"
MIRROR_DIR="$DIR/.mirror"
MIRROR_TOOLS_IMAGE="erp-mirror-tools:1"
MIRROR_APP_SERVICES="backend frontend websocket scheduler queue-short queue-long"
export MIRROR_DIR

case "$MIRROR_ROLE" in
  primary) MIRROR_COMPOSE_FILE="$DIR/docker-compose.mirror-primary.yml" ;;
  replica) MIRROR_COMPOSE_FILE="$DIR/docker-compose.mirror-replica.yml" ;;
  "") MIRROR_COMPOSE_FILE="" ;;
  *)
    echo "ERROR: MIRROR_ROLE in .mirror.env must be 'primary' or 'replica', got '$MIRROR_ROLE'."
    exit 1
    ;;
esac

mirror_state() {
  cat "$MIRROR_DIR/state" 2>/dev/null || echo standby
}

# Files in .mirror/ are also written by the root-owned sidecar, so replace
# them instead of writing in place.
mirror_write() {
  mkdir -p "$MIRROR_DIR"
  printf '%s\n' "$2" > "$MIRROR_DIR/$1.tmp"
  mv -f "$MIRROR_DIR/$1.tmp" "$MIRROR_DIR/$1"
}

mirror_require_role() {
  if [ "$MIRROR_ROLE" != "$1" ]; then
    echo "ERROR: this command runs on the $1 host (MIRROR_ROLE=$1 in .mirror.env); here MIRROR_ROLE='$MIRROR_ROLE'."
    exit 1
  fi
}

# A standby mirror's database is a replica: anything that migrates or restores
# would write into it. A fenced main has been replaced by the mirror: starting
# it again would let users write to both.
mirror_guard() {
  case "$MIRROR_ROLE" in
    replica)
      if [ "$(mirror_state)" != "active" ]; then
        echo "ERROR: '$1' is disabled on a standby mirror (its database is a replica of main)."
        echo "Update code with './deploy mirror sync-code'; take over with './deploy mirror start'."
        exit 1
      fi
      ;;
    primary)
      if [ -f "$MIRROR_DIR/fenced" ]; then
        echo "ERROR: '$1' is disabled: the mirror took over while this server was unreachable."
        echo "Run './deploy mirror failback' on the mirror, or './deploy mirror unfence' here to abandon the mirror's changes."
        exit 1
      fi
      ;;
  esac
}

mirror_sql() {
  dc exec -T db mariadb -uroot -padmin "$@"
}

mirror_tool() {
  dc run --rm -T --no-deps mirror-files mirror "$@"
}

mirror_site_value() {
  python3 -c "import json, sys; c = json.load(sys.stdin); print(c.get('$1') or c.get('$2', ''))"
}

# Replaces the mirror's copy of the site database with a fresh dump of main's
# and points replication at the GTID the dump was taken at. Works both for the
# first setup and to rejoin after a failback.
mirror_seed() {
  local config db_name db_user db_password
  : "${MIRROR_REPL_USER:?set MIRROR_REPL_USER in .mirror.env}"
  : "${MIRROR_REPL_PASSWORD:?set MIRROR_REPL_PASSWORD in .mirror.env}"

  say "==> Copying site config from main..."
  mirror_tool pull-config
  config=$(mirror_tool site-config)
  db_name=$(printf '%s' "$config" | mirror_site_value db_name db_name)
  db_user=$(printf '%s' "$config" | mirror_site_value db_user db_name)
  db_password=$(printf '%s' "$config" | mirror_site_value db_password db_password)
  if [ -z "$db_name" ] || [ -z "$db_password" ]; then
    echo "ERROR: main's site_config.json has no db_name/db_password."
    exit 1
  fi

  say "==> Pointing replication at main..."
  mirror_sql -e "STOP SLAVE; RESET SLAVE ALL; SET GLOBAL read_only=1;
    CHANGE MASTER TO MASTER_HOST='mirror-tunnel', MASTER_PORT=3306,
      MASTER_USER='$MIRROR_REPL_USER', MASTER_PASSWORD='$MIRROR_REPL_PASSWORD',
      MASTER_CONNECT_RETRY=10;"

  say "==> Copying database $db_name from main (this takes a while)..."
  (set -o pipefail; mirror_tool dump | gunzip | mirror_sql)

  mirror_sql -e "CREATE USER IF NOT EXISTS '$db_user'@'%' IDENTIFIED BY '$db_password';
    ALTER USER '$db_user'@'%' IDENTIFIED BY '$db_password';
    GRANT ALL PRIVILEGES ON \`$db_name\`.* TO '$db_user'@'%';
    FLUSH PRIVILEGES;
    CHANGE MASTER TO MASTER_USE_GTID=slave_pos;
    START SLAVE;"
  say "==> Replication started."
}

mirror_join() {
  say "==> Starting database and tunnel..."
  dc build mirror-tunnel
  dc up -d db redis-cache redis-queue mirror-tunnel
  wait_for_db
  mirror_seed
  say "==> Copying attachments from main (first run copies everything)..."
  mirror_tool pull-files
  mirror_tool primary-commit
  dc up -d mirror-files
}

mirror_status() {
  echo "Role: ${MIRROR_ROLE:-none}"
  case "$MIRROR_ROLE" in
    primary)
      if [ -f "$MIRROR_DIR/fenced" ]; then
        echo "State: FENCED since $(cat "$MIRROR_DIR/fenced") — the mirror is serving; run failback there."
      else
        echo "State: serving"
      fi
      mirror_sql -e "SHOW MASTER STATUS\G" | grep -E "File|Position" || echo "Binary log: OFF"
      mirror_sql -N -e "SHOW BINARY LOGS" 2>/dev/null |
        awk '{s += $2} END {printf "Binary logs: %d files, %.1f MB\n", NR, s / 1048576}'
      ;;
    replica)
      local state files_ok primary built
      state=$(mirror_state)
      echo "State: $state"
      [ "$state" = "active" ] && echo "Active since: $(cat "$MIRROR_DIR/active-since" 2>/dev/null)"
      mirror_sql -e "SHOW SLAVE STATUS\G" |
        grep -E "Slave_IO_Running|Slave_SQL_Running:|Seconds_Behind_Master|Last_IO_Error|Last_SQL_Error|Gtid_IO_Pos" ||
        echo "Replication: not configured"
      files_ok=$(cat "$MIRROR_DIR/files-ok" 2>/dev/null || echo "")
      if [ -n "$files_ok" ]; then
        echo "Files synced: $(( $(date +%s) - files_ok ))s ago"
      else
        echo "Files synced: never"
      fi
      primary=$(cat "$MIRROR_DIR/primary-commit" 2>/dev/null || echo "?")
      built=$(cat "$MIRROR_DIR/built-commit" 2>/dev/null || echo "?")
      echo "Main code:   $primary"
      echo "Mirror code: $built"
      [ "$primary" = "$built" ] || echo "WARNING: code differs from main — run './deploy mirror sync-code'."
      ;;
    *)
      echo "Mirror is not configured (no MIRROR_ROLE in .mirror.env)."
      ;;
  esac
}

mirror_confirm() {
  local answer
  printf "%s Type the site name (%s) to proceed: " "$1" "$SITE"
  read -r answer </dev/tty
  [ "$answer" = "$SITE" ] || { echo "Aborted."; exit 1; }
}

mirror_command() {
  local sub="${1:-}"
  shift || true
  local force=0 yes=0 arg
  for arg in "$@"; do
    case "$arg" in
      --force) force=1 ;;
      --yes) yes=1 ;;
    esac
  done

  case "$sub" in
    status) mirror_status ;;

    primary-setup)
      mirror_require_role primary
      : "${MIRROR_REPL_USER:?set MIRROR_REPL_USER in .mirror.env}"
      : "${MIRROR_REPL_PASSWORD:?set MIRROR_REPL_PASSWORD in .mirror.env}"
      mkdir -p "$MIRROR_DIR"
      wait_for_db
      if ! mirror_sql -N -e "SELECT @@log_bin" | grep -q 1; then
        echo "ERROR: binary log is off. Run './deploy build --silent' once so db picks up docker-compose.mirror-primary.yml."
        exit 1
      fi
      say "==> Building mirror tools image (used for rsync)..."
      docker build -q -t "$MIRROR_TOOLS_IMAGE" "$DIR/tools/mirror" >/dev/null
      mirror_sql -e "CREATE USER IF NOT EXISTS '$MIRROR_REPL_USER'@'%' IDENTIFIED BY '$MIRROR_REPL_PASSWORD';
        ALTER USER '$MIRROR_REPL_USER'@'%' IDENTIFIED BY '$MIRROR_REPL_PASSWORD';
        GRANT REPLICATION SLAVE ON *.* TO '$MIRROR_REPL_USER'@'%';
        FLUSH PRIVILEGES;"
      echo "Main is ready for a mirror."
      mirror_status
      ;;

    # --- Called by the mirror over SSH on main ---------------------------
    dump)
      mirror_require_role primary
      local db_name
      db_name=$(dc exec -T backend cat "/home/frappe/frappe-bench/sites/$SITE/site_config.json" | mirror_site_value db_name db_name)
      set -o pipefail
      dc exec -T db mariadb-dump -uroot -padmin --single-transaction --gtid --master-data=1 \
        --routines --events --triggers --add-drop-database --databases "$db_name" | gzip -1
      ;;

    rsync-server)
      mirror_require_role primary
      exec docker run --rm -i -v docker_sites:/home/frappe/frappe-bench/sites "$MIRROR_TOOLS_IMAGE" rsync "$@"
      ;;

    fence)
      mirror_require_role primary
      [ -f "$MIRROR_DIR/fenced" ] || mirror_write fenced "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      # backend stays up: failback restores through it.
      dc stop frontend websocket scheduler queue-short queue-long >/dev/null 2>&1 || true
      echo "Main fenced: users cannot reach it until './deploy mirror unfence'."
      ;;

    unfence)
      mirror_require_role primary
      rm -f "$MIRROR_DIR/fenced"
      dc up -d >/dev/null 2>&1
      fix_assets >/dev/null 2>&1 || true
      echo "Main unfenced and serving."
      ;;

    # --- Mirror host --------------------------------------------------------
    setup)
      mirror_require_role replica
      if [ "$(mirror_state)" = "active" ]; then
        echo "ERROR: the mirror is serving users. Run './deploy mirror failback' first — setup would discard their work."
        exit 1
      fi
      mkdir -p "$MIRROR_DIR"
      mirror_tool reachable >/dev/null || { echo "ERROR: cannot SSH to $MIRROR_PRIMARY_SSH."; exit 1; }
      dc stop $MIRROR_APP_SERVICES >/dev/null 2>&1 || true
      mirror_join
      mirror_write state standby
      echo "Mirror is in standby."
      mirror_status
      [ -f "$MIRROR_DIR/built-commit" ] || echo "Next: './deploy mirror sync-code' to build main's code here."
      ;;

    sync-code)
      mirror_require_role replica
      local commit
      mirror_tool primary-commit 2>/dev/null || echo "WARNING: main unreachable, using last known commit."
      commit=$(cat "$MIRROR_DIR/primary-commit" 2>/dev/null || true)
      [ -n "$commit" ] || { echo "ERROR: main's commit is unknown — run './deploy mirror setup' first."; exit 1; }
      if [ -n "$(git -C "$DIR" status --porcelain --untracked-files=no)" ]; then
        echo "ERROR: local changes in $DIR — the mirror must run main's exact code."
        exit 1
      fi
      say "==> Checking out $commit..."
      git -C "$DIR" fetch --quiet origin
      git -C "$DIR" checkout --quiet --detach "$commit"
      git -C "$DIR" submodule update --init --quiet
      # The checkout may have replaced this script; continue in the new one.
      exec "$DIR/deploy" mirror build-image "$commit"
      ;;

    build-image)
      mirror_require_role replica
      local commit="${1:?usage: ./deploy mirror build-image <commit>}"
      local build_log
      build_log=$(mktemp)
      say "==> Building image (log: $build_log)..."
      if ! build_image >"$build_log" 2>&1; then
        echo "ERROR: docker build failed. Last 30 lines:"
        tail -30 "$build_log"
        exit 1
      fi
      rm -f "$build_log"
      mirror_write built-commit "$commit"
      echo "Mirror image built from $commit."
      if [ "$(mirror_state)" = "active" ]; then
        echo "The mirror is serving: apply it with './deploy build --silent'."
      fi
      ;;

    start)
      mirror_require_role replica
      if [ "$(mirror_state)" = "active" ]; then
        echo "The mirror is already serving at ${PUBLIC_SERVER_URL:-http://localhost:8080}."
        exit 0
      fi
      if [ "$force" != "1" ] && mirror_tool reachable >/dev/null 2>&1; then
        echo "ERROR: main is reachable. Taking over now would split users between two databases."
        echo "If main is up but broken, rerun with --force."
        exit 1
      fi
      local primary built
      primary=$(cat "$MIRROR_DIR/primary-commit" 2>/dev/null || echo "")
      built=$(cat "$MIRROR_DIR/built-commit" 2>/dev/null || echo "")
      if [ "$force" != "1" ] && { [ -z "$built" ] || [ "$primary" != "$built" ]; }; then
        echo "ERROR: mirror image ($built) is not main's code ($primary). Run './deploy mirror sync-code' or pass --force."
        exit 1
      fi

      say "==> Detaching the database from main..."
      dc up -d db
      wait_for_db
      mirror_sql -e "SHOW SLAVE STATUS\G" | grep -E "Seconds_Behind_Master|Gtid_IO_Pos" || true
      mirror_sql -e "STOP SLAVE; RESET SLAVE ALL; SET GLOBAL read_only=0;"
      mirror_write active-since "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      mirror_write state active

      say "==> Starting ERPNext..."
      dc up -d
      dc wait configurator >/dev/null 2>&1 || sleep 5
      sync_built_assets
      apply_site_config
      wait_for_backend
      dc exec -T backend bench --site "$SITE" set-maintenance-mode off
      dc exec -T backend bench --site "$SITE" clear-cache
      ensure_assets_manifest
      fix_assets
      echo ""
      echo "MIRROR IS SERVING at ${PUBLIC_SERVER_URL:-http://<this-host>:8080}"
      echo "Point browsers and the Android app there. When main is back: './deploy mirror failback'."
      ;;

    failback)
      mirror_require_role replica
      if [ "$(mirror_state)" != "active" ]; then
        echo "ERROR: the mirror is not serving; nothing to fail back."
        exit 1
      fi
      mirror_tool reachable >/dev/null || { echo "ERROR: cannot SSH to main yet."; exit 1; }
      echo "!! FAILBACK REPLACES MAIN'S DATABASE WITH THIS MIRROR'S."
      echo "!! Main keeps a safety backup of its own database first."
      [ "$yes" = "1" ] || mirror_confirm "Mirror active since $(cat "$MIRROR_DIR/active-since" 2>/dev/null)."
      trap 'echo "ERROR: failback stopped. Main stays fenced, mirror in maintenance mode. Fix the cause and rerun ./deploy mirror failback."' ERR

      say "==> Fencing main..."
      mirror_tool fence
      say "==> Freezing the mirror..."
      dc exec -T backend bench --site "$SITE" set-maintenance-mode on
      dc stop frontend websocket scheduler queue-short queue-long

      say "==> Backing up the mirror database..."
      dc exec -T backend bench --site "$SITE" backup
      local name
      name=$(backup_list | tail -1 | awk '{print $1}')
      [ -n "$name" ] || { echo "ERROR: backup produced no set."; exit 1; }

      say "==> Copying backup $name and attachments to main..."
      mirror_tool push-backup "$name"
      mirror_tool push-files

      say "==> Restoring $name on main..."
      mirror_tool restore "$name"
      mirror_tool unfence
      trap - ERR

      # Main is serving again from here: never let a rerun restore over it.
      mirror_write state standby
      rm -f "$MIRROR_DIR/active-since"

      say "==> Returning the mirror to standby..."
      dc stop $MIRROR_APP_SERVICES
      if ! mirror_join; then
        echo "WARNING: main is serving, but the mirror could not rejoin. Rerun './deploy mirror setup'."
        exit 1
      fi
      echo "Failback complete: main is serving, the mirror is in standby."
      mirror_status
      ;;

    stop)
      mirror_require_role replica
      if [ "$(mirror_state)" = "active" ]; then
        echo "WARNING: the mirror is serving; this only stops the app. Its data stays until failback."
      fi
      dc stop $MIRROR_APP_SERVICES
      ;;

    *)
      cat <<'USAGE'
Usage: ./deploy mirror <command>
  Main (MIRROR_ROLE=primary):
    primary-setup       create the replication account (after one ./deploy build)
    status              binary log size, fenced or serving
    unfence             serve again without failback (discards the mirror's changes)
  Mirror (MIRROR_ROLE=replica):
    setup               copy main's database + files and start replicating
    sync-code           check out and build main's code
    status              replication lag, file sync age, code match
    start [--force]     take over while main is unreachable
    failback [--yes]    copy the mirror's data back to main, return to standby
    stop                stop the app containers
USAGE
      exit 1
      ;;
  esac
}
