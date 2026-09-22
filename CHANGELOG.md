# Changelog

Versions are calendar versions `YYYY.MM.DD.N`; tags carry no prefix. A merge
to `main` publishes the release; see `docs/operations.md`.

## 2026.09.22.3

First live log review (El Rancho Assist, 2026-09-22 11:45 to 12:00):

- A device with no Cast channel at all (the Master Google mini, which
  pychromecast could not connect to on 8009 for the whole window) stayed at
  `unknown` because the probe skipped unavailable devices silently. The
  probe now records `unreachable` for them, and a new self-resolving repair
  issue `cast_device_unreachable` is raised after two consecutive
  `unreachable` outcomes, naming the host and the 8009 check.
- `RequestFailed` from pychromecast covers both "message not sent" and
  "device answered LAUNCH_ERROR". The Media Closet speaker was answering
  within half a second and being reported `unreachable`. When the entity is
  connected the outcome is now `fetch_failed` with the receiver's last
  launch failure (`reason=... app_id=...`) in the error text.

## 2026.09.22.2

- Harness and stubs moved to core 2026.9.3 (Dependabot bumps merged).
- Entry unload removes the discovery stop listener from the executor and
  clears the browser before the blocking stop, fixing a race with the
  Home Assistant stop event (`release unlocked lock`).
- Dependabot: codeql-action 4.38.1, hassfest action refreshed, ruff 0.16.8.

## 2026.09.22.1

### WP0, fork hygiene and provenance

- Forked `homeassistant/components/cast` verbatim from core tag `2026.9.2`
  (`33c3e0cca60e`); provenance and sync procedure in `UPSTREAM.md`.
- Ported core's 88 cast tests to `pytest-homeassistant-custom-component`
  and added a load test.
- Added the release and security baseline: ruff, strict mypy, pytest with
  coverage, hassfest and HACS validation, CodeQL and bandit, merge-to-main
  releases with SBOM, checksums, and attestations.

### WP1, failure becomes state

- New `health.py`: a delivery ledger keyed on the content id we requested,
  the closed outcome vocabulary (`ok`, `fetch_failed`, `unreachable`,
  `timeout`, `template_error`, `skipped_busy`, `unknown`), a 30 s
  state-transition timer, and structured debug logging of every decision.
- New `sensor.py`: `sensor.<device>_tts_outcome` (enum, with the evidence
  as attributes) and `sensor.<device>_last_tts_success` (timestamp, restored
  across restarts) on every cast device.
- Event `cast_delivery_result` fired for every resolved record.
- Every `quick_play` call runs behind a 45 s watchdog; an expiry records
  `timeout` and raises a translated error.
- `async_unload_entry` added; discovery stops and the lock is released on
  unload.
- Strict typing across the inherited files; mypy strict is a required check.
- 16 new tests, including `test_mdns_visible_but_unreachable`,
  `test_timeout_not_recorded_as_success`,
  `test_stale_metadata_not_treated_as_confirmation`, and the watchdog test.

### WP2, active reachability probing

- New `coordinator.py`: probes every idle audio device on a configurable
  interval (default 300 s, floor 60 s) off the coordinator's critical path,
  behind a 20 s watchdog, with a per-device circuit breaker (two consecutive
  timeouts, exponential backoff capped at one hour) and a `skipped_busy`
  outcome that never interrupts playback.
- New `probe.py`: an unauthenticated view serving a quarter second of
  silence under a per-start token, played through the same URL selection as
  TTS.
- Options section "Delivery health": `probe_enabled`, `probe_interval`,
  `group_probe_enabled` (pychromecast #1197), `probe_video_devices` (off, CEC).
- The entry update listener now lives in `async_setup_entry` and is removed
  on unload, so reloads do not accumulate listeners.
- 14 new tests, including `test_hung_device_does_not_block_others` and
  `test_circuit_breaker_opens`.

### WP3, topology and subnet awareness

- New `topology.py`: group leader IP, uuid, advertised port, and members
  from the multizone manager; adapter-based subnet placement; leader moves
  logged.
- `sensor.<group>_leader` on configured groups with `leader_uuid`,
  `member_uuids`, `member_ips`, `subnets`, `members_span_subnets`,
  `advertised_port`, `is_dynamic_group`.
- `subnet_mismatch` on every outcome sensor; a mismatch never changes the
  outcome.
- Group probing stays independently switchable (`group_probe_enabled`).
- 6 new tests including `test_leader_migration_detected` (inside
  `test_group_leader_sensor_and_subnets`).

### WP4, diagnostics, repairs, and registry hygiene

- New `issues.py` and `repairs.py`: five self-resolving repair issues
  (`tts_fetch_failed`, `internal_url_automatic_multihomed`,
  `cast_group_spans_subnets`, `stale_cast_device` with a removal fix flow,
  `tts_template_error`), each naming the device and the next action, with
  discovery timestamps persisted in `.storage/cast.health`.
- New `diagnostics.py`: URLs with adapter and pinning, every device's
  outcome and placement, groups, the last 50 ledger records, registry
  devices without discovery, probe decisions, active issues; external URL
  and user id redacted.
- New `cast.announce` action (`services.py`, `CastMediaPlayerEntity.async_announce`):
  renders the message template itself so a failure is a `template_error`
  outcome and issue; tracks the delivery as `source=announce`.
- `icons.json` entity icons per outcome; `quality_scale.yaml` with every
  rule marked done or exempt with a reason.
- 10 new tests including `test_repair_autoresolves` behavior for every
  issue and the stale device fix flow over the repairs HTTP API.

### WP5, documentation and release tooling

- `README.md`, `docs/troubleshooting.md` (from "the speaker said nothing"
  to a cause using only the fork's entities and diagnostics),
  `docs/operations.md`, `docs/README.md`, `THREAT-MODEL.md`.
- Blueprint `blueprints/automation/trooperthorn/cast_delivery_alert.yaml`
  turning `cast_delivery_result` failures into notifications.
- Release tooling: CalVer `YYYY.MM.DD.N` with no tag prefix, manifest and
  tag bumped in lockstep by `scripts/set_version.py`, validated by
  `scripts/build_release_artifacts.py`; HACS installs `cast.zip` from the
  GitHub Release with SBOM, checksums, and attestations.
- `network` added to `after_dependencies` (hassfest).

### Divergence from upstream

Inherited files edited by the fork, so an upstream reconciliation knows
where to look:

- `manifest.json`: `codeowners`, `documentation`, `issue_tracker`, `version`.
- `__init__.py`: `Platform.SENSOR`, `ledger`, `added_health_devices`, and
  `unsub_discovery_stop` on `CastRuntimeData`, `async_unload_entry`.
- `const.py`: fork constants appended.
- `discovery.py`: type annotations, ledger identity update on discovery,
  `stop_internal_discovery`.
- `helpers.py`: type annotations only.
- `media_player.py`: type annotations, no-op callback stubs on `CastDevice`,
  the `_ledger` property, ledger calls in `new_media_status` and
  `load_media_failed`, `_async_quick_play_tracked` replacing the two direct
  `quick_play` executor calls.
- `config_flow.py`: the "Delivery health" options section, stored in
  `entry.options`.
- `discovery.py`: the update listener registration moved to `__init__.py`;
  `config_entry_updated` also applies probe options.
- `strings.json`: `entity` block, `options` health section, and the
  `request_watchdog` and `probe_watchdog` exceptions.
- Import order follows this repository's ruff configuration.
