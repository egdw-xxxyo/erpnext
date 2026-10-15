#!/bin/bash
# Frontend (nginx) start and config render. Replaces the image's
# nginx-entrypoint.sh so the template can live in the repo and be re-applied
# with a reload instead of a container restart.
#
#   entrypoint.sh           render the config and run nginx in the foreground
#   entrypoint.sh render    render, test, and keep the old config if the new
#                           one does not pass `nginx -t`
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF=/etc/nginx/conf.d/frappe.conf
RESOLVER_CONF=/etc/nginx/conf.d/00-resolver.conf

export FRAPPE_SITE_NAME_HEADER="${FRAPPE_SITE_NAME_HEADER:-\$host}"
export UPSTREAM_REAL_IP_ADDRESS="${UPSTREAM_REAL_IP_ADDRESS:-127.0.0.1}"
export UPSTREAM_REAL_IP_HEADER="${UPSTREAM_REAL_IP_HEADER:-X-Forwarded-For}"
export UPSTREAM_REAL_IP_RECURSIVE="${UPSTREAM_REAL_IP_RECURSIVE:-off}"
export PROXY_READ_TIMEOUT="${PROXY_READ_TIMEOUT:-120}"
export CLIENT_MAX_BODY_SIZE="${CLIENT_MAX_BODY_SIZE:-50m}"

render() {
  # The container's own DNS server: 127.0.0.11 under docker, the network
  # gateway under podman. valid=10s caps how long a stale address is used.
  # ipv6=off: the embedded resolver answers AAAA with nothing and nginx logs an
  # error for every lookup otherwise.
  local ns
  ns=$(awk '$1 == "nameserver" {print $2; exit}' /etc/resolv.conf)
  case "$ns" in *:*) ns="[$ns]" ;; esac
  printf 'resolver %s valid=10s ipv6=off;\nresolver_timeout 5s;\n' "${ns:-127.0.0.11}" >"$RESOLVER_CONF"

  # shellcheck disable=SC2016
  envsubst '${FRAPPE_SITE_NAME_HEADER}
    ${UPSTREAM_REAL_IP_ADDRESS}
    ${UPSTREAM_REAL_IP_HEADER}
    ${UPSTREAM_REAL_IP_RECURSIVE}
    ${PROXY_READ_TIMEOUT}
    ${CLIENT_MAX_BODY_SIZE}' <"$HERE/frappe.conf.template" >"$CONF"
}

if [ "${1:-}" = "render" ]; then
  # Not *.conf, so nginx does not include the copy.
  [ -f "$CONF" ] && cp "$CONF" "$CONF.prev"
  render
  if ! nginx -t; then
    [ -f "$CONF.prev" ] && cp "$CONF.prev" "$CONF"
    exit 1
  fi
  exit 0
fi

render
# worker_shutdown_timeout: after a reload, workers of the previous config would
# otherwise live for as long as a websocket stays open, i.e. indefinitely, and a
# cutover could never tell when the previous backend is idle. After 25s they
# close what is left; socket.io reconnects on its own.
exec nginx -g 'daemon off; worker_shutdown_timeout 25s;'
