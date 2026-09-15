# Milestone markers for the ops dashboard, sourced by ./deploy and ./updateRepo.
#
# Format: [OPS] <utc-iso8601> <phase> <start|ok|fail|skip> <human text>
#
# Two sinks on purpose. The stdout copy lands in the job log the console
# streams, so a human reading the raw output sees the same milestones. The
# OPS_PHASE_LOG copy (exported by the ops job runner) is what the dashboard
# polls — reading a 20-line side file instead of grepping a 50 MB build log
# every few seconds.
#
# Markers must be emitted from an unredirected place: under --silent most steps
# route their own stdout to /dev/null, which would swallow the stdout copy.

OPS_PHASE_LOG="${OPS_PHASE_LOG:-}"

ops_step() {
  local phase="$1" mark="$2"
  shift 2
  local line="[OPS] $(date -u +%Y-%m-%dT%H:%M:%SZ) $phase $mark $*"
  echo "$line"
  if [ -n "$OPS_PHASE_LOG" ]; then
    printf '%s\n' "$line" >>"$OPS_PHASE_LOG" 2>/dev/null || true
  fi
}
