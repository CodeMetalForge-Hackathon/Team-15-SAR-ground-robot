"""Wires authenticated BLE-ID verification into the standalone discovery server.

Verification is opt-in and explicit: --keys PATH (production) or --test-keys
(PUBLIC SYNTHETIC TEST KEYS, visibly labelled), plus --state and --scope. With
neither, the page shows "verification off" and discovery behaves as before.
Startup problems (keys, scope, missing/corrupt state, second owner) exit with an
error instead of serving unverified results as if they were verified.
"""
from __future__ import annotations

import sys

from ble_id import BeaconMonitor, OwnerError
from ble_keys import KeyConfigError, keys_for
from ble_state import StateError

OFF = dict(status="off", source=None, mode=None, mode_label="VERIFICATION OFF", sightings=[], counts={},
           events=[], detail="Authenticated verification is off. Start with --keys or --test-keys.")


def add_arguments(parser):
    g = parser.add_argument_group("authenticated beacon verification (optional)")
    x = g.add_mutually_exclusive_group()
    x.add_argument("--keys", help="production keys.json (chmod 600); synthetic test keys are refused")
    x.add_argument("--test-keys", action="store_true",
                   help="use the PUBLIC SYNTHETIC TEST KEYS; labelled experiment, scope must start TESTKEY-")
    g.add_argument("--state", help="replay state file, created beforehand with: python3 -m ble_id init-state")
    g.add_argument("--scope", help="enrollment/mission scope that the keys and state belong to")


def monitor_from_args(args, discovery, *, source="LIVE-HW"):
    """None when verification was not requested; otherwise a BeaconMonitor or SystemExit."""
    if not args.keys and not args.test_keys:
        if args.state or args.scope:
            sys.exit("ERROR: --state/--scope given without --keys or --test-keys")
        return None
    if not args.state or not args.scope:
        sys.exit("ERROR: verification needs --state and --scope")
    mode = "production" if args.keys else "test-keys"
    try:
        keys = keys_for(mode, scope=args.scope, path=args.keys)
        return BeaconMonitor(keys, args.state, scope=args.scope, mode=mode, source=source,
                             receiver_ready=discovery.ready)
    except (KeyConfigError, StateError, OwnerError) as exc:
        sys.exit(f"ERROR: verification not started: {exc}")


def snapshot(monitor, discovery):
    data = dict(OFF) if monitor is None else monitor.snapshot()
    d = discovery.snapshot()
    data["receiver"] = dict(status=d["status"], detail=d["detail"], source=d["source"])
    return data
