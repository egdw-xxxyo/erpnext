"""Reviewed source of truth for the `Spool QC` Workplace Script stored in the database.

    Workplace Script: Spool QC
    workplace:        (set per bench, or left empty as the site-wide default)

The database copy is what actually executes — this file exists so the body is versioned,
linted and reviewable, the same arrangement the Reflectometer script used before it.

Two pieces go into the Workplace Script:

1. the main script (parent `script` field), which only dispatches to the current state;
2. one state, `measuring`, marked Initial, whose On Enter script does the work.

A single state is enough today: a measurement is self-contained, so the machine never has
to remember anything between traces. The state machine is still worth going through — it is
where a bench gets a second step later (re-measure on a marginal result, require a
supervisor scan before accepting an override) without touching Python.
"""

MAIN_SCRIPT = """
from erpnext.devices.doctype.workplace_script.workplace_script import run_state


def on_measurement(e):
    return run_state("Spool QC", e, scripts=scripts, handler="on_measurement")
"""


STATE_MEASURING = """
from erpnext.devices.spool_qc import handle_measurement


def on_measurement(e):
    return handle_measurement(e)
"""
