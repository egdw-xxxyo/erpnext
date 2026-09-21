# Milestone markers for the ops dashboard, sourced by ./deploy and ./updateRepo.
#
# Format: [OPS] <utc-iso8601> <phase> <start|ok|fail|skip> <human text>
#
# Two sinks on purpose. The job-log copy sits inline with the command output,
# so a human reading the raw log sees the same milestones — and the dashboard
# can jump from a step row straight to the line that step printed. The
# OPS_PHASE_LOG copy is what the dashboard polls — reading a 20-line side file
# instead of grepping a 50 MB build log every few seconds.
#
# The job-log copy is written to the file, not echoed to stdout: under --silent
# most steps route their own stdout to /dev/null, which swallowed all but the
# last few markers. Both writers open the log O_APPEND, and a marker is one
# short line, so it lands whole between chunks of command output.
#
# Outside a job (an operator running ./deploy in a terminal) neither variable
# is set and the marker goes to stdout, as before.

OPS_PHASE_LOG="${OPS_PHASE_LOG:-}"
OPS_JOB_LOG="${OPS_JOB_LOG:-}"

ops_step() {
  local phase="$1" mark="$2"
  shift 2
  local line="[OPS] $(date -u +%Y-%m-%dT%H:%M:%SZ) $phase $mark $*"
  if [ -n "$OPS_JOB_LOG" ]; then
    printf '%s\n' "$line" >>"$OPS_JOB_LOG" 2>/dev/null || true
  else
    echo "$line"
  fi
  if [ -n "$OPS_PHASE_LOG" ]; then
    printf '%s\n' "$line" >>"$OPS_PHASE_LOG" 2>/dev/null || true
  fi
}
