# Appliance state recovery

This branch addresses stale connection/door readings and laundry cycle switches
remaining on after completion. It is a development build, not a guarantee of
connectivity to Haier's cloud. No appliance start/stop command is part of recovery.

## Changes

- Retry initial setup automatically through Home Assistant's backoff when DNS,
  a connection, or a request times out before the recovery coordinator exists.
  Close the failed client before retrying. Authentication and other non-transport
  errors are not silently converted into connectivity failures.
- Refresh every appliance through REST every five minutes, independently of MQTT
  pushes and changes to settings. A busy appliance cannot postpone another one's
  fallback refresh.
- Bound each request to 30 seconds. Continue refreshing other appliances after a
  failure, mark failed device readings unavailable, and recover on a later success.
- Keep program selections: refresh telemetry and the library's `settings` command,
  not the pending `startProgram` settings.
- Cancel timers/in-flight recovery and close the library's MQTT client on unload.
- The companion library synchronizes connection events with the connection sensor,
  recalculates laundry active/pause/program state after MQTT updates, handles new
  parameters and malformed messages, and dispatches messages on the asyncio loop.
- A REST snapshot fetched before a newer push is discarded rather than overwriting
  that update. Newer cloud snapshots can still be stale at their source.

The manifest pins the companion library to an immutable commit and an explicit
development version. Install this branch only as a deliberate test deployment.
Version `0.19.3.dev1` adds startup retry to the state recovery in `0.19.3.dev0`;
updating the integration's Python code requires a Home Assistant restart.

## Comparison reviewed

- [mmalolepszy/hon-revived](https://github.com/mmalolepszy/hon-revived): kept as the
  base because it is the installed integration family. Its main branch already has
  a newer library watchdog fix beyond the released 0.19.2 library.
- [Existing stale connectivity report](https://github.com/mmalolepszy/hon-revived/issues/34)
  and [missed wash updates](https://github.com/mmalolepszy/hon-revived/issues/55)
  match the classes of symptom addressed here.
- [Odyno's contribution](https://github.com/mmalolepszy/hon-revived/pull/64) adds a
  five-minute coordinator polling fallback and lifecycle cleanup, with many other
  changes. It is a useful direction, but a shared coordinator's ordinary polling
  deadline is reset by `async_set_updated_data`, so frequent pushes can postpone
  it. This branch keeps a separate timer and preserves entity unique IDs.
- [Odyno/pyhon-revived](https://github.com/Odyno/pyhon-revived) also addresses MQTT
  cleanup, malformed messages and scalar attribute comparisons. This branch limits
  its changes to state freshness and lifecycle rather than taking the full refactor.
- [rwsender/hon-revived](https://github.com/rwsender/hon-revived) adds a stock-program
  start service; its setup still uses push-only state updates.
- [gvigroux/hon](https://github.com/gvigroux/hon) uses coordinators and explicit
  refreshes in its own implementation. Moving integrations would require a separate
  device/entity compatibility review; it is not established as a better replacement.
- [Andre0512/hon](https://github.com/Andre0512/hon) is the original project; its
  reported latest push is from 2024, so it is not a freshness upgrade over Revived.

## Validation

Run `python -m pytest -q` with Home Assistant, the pinned companion library, pytest
and pytest-asyncio installed. Tests use fake appliances and a real HA coordinator;
they never log into hOn or start an appliance. Startup tests cover DNS errors,
connection failures and timeouts, including cleanup failure, without leaving
timers or partial runtime state. Companion-library tests cover live
connection synchronization, cycle completion, pause, door state, missed pushes,
thread dispatch, malformed messages, snapshot races and shutdown cleanup.

Current HA compatibility is checked by the State regression tests GitHub workflow.
The targeted tests pass on Home Assistant 2026.9.0, and HACS/hassfest validation
passes. The recovery branches now include the forks' latest CI repairs. Library quality
checks run all 25 combined regression cases; the integration uses the same exact
library build in its manifest and requirements file. Baseline return-type,
complexity, formatting and typing failures have been repaired without relaxing
production lint limits. Hosted results are recorded in the recovery PRs.
Actual cloud outages, unavailable Wi-Fi and machine-side refusal can still prevent
updates or starts. The dashboard should continue to require appliance confirmation.

## Combined upstream upgrade candidate

Integration `0.19.6.dev0` incorporates upstream hOn `v0.19.5` while retaining
independent five-minute REST recovery, startup retries, per-device availability,
selection preservation and unload cleanup. It pins companion library
`0.19.5.dev0` at commit `b358a9dd3280bb27ad403a18e03891e6327025db`.
That library combines upstream pyhon `v0.19.4` with the existing MQTT connection,
laundry completion, snapshot-race and lifecycle fixes. Upstream program-value
normalization and diagnostic export fixes are retained and regression tested.

The state-regression workflow now targets Home Assistant `2026.11.1`, matching
the installed instance reviewed for this upgrade. This candidate must be
published together with its pinned library commit before installing from GitHub.
A local test does not verify a real Haier cloud session or appliance behavior;
keep the previous integration files and exact library pin available for rollback,
restart Home Assistant after installation, and verify a complete wash/dry cycle.
HACS's upstream version record does not describe a manually installed fork.

### Local validation of the combined candidate

- Python 3.14 with Home Assistant 2026.11.1 and the built companion package:
  all 12 integration tests pass, including all ten platform imports and washer/
  dryer entity completion, availability, stable unique IDs and disconnection.
- The combined library passes all 30 tests plus five unittest subtests, including
  uppercase wire values/case-insensitive triggers and diagnostic archive fixes.
- The original offline washer/dryer MQTT reproductions now both show inactive
  cycles after completion and a disconnected connection-sensor snapshot.
- Library flake8, mypy, Pylint and Black pass; integration syntax lint and Black
  pass; pip check reports no broken requirements.
- Against HA 2026.11.1, integration mypy reports 14 existing errors in config-flow
  schemas/result types, legacy climate temperature APIs and two obsolete import
  ignores. The unchanged fork produces the same 14 errors. These are not hidden
  or relaxed in this upgrade; the upstream unit-fallback typing issues are fixed.
- Existing datetime.utcnow deprecation warnings remain in library auth tests;
  the HA HTTP application inheritance warning also remains in integration tests.
- Windows tests normalize HA's POSIX-only frame lookup and register integration
  metadata for platform imports. Production code is not patched for the test OS.

This establishes offline regression compatibility, not a guarantee of Haier cloud
availability or a real appliance cycle. No live HA installation, restart, login or
appliance command was performed as part of this candidate validation.
