# Changelog

Versions are calendar versions `YYYY.MM.DD.N`; tags carry no prefix. A merge
to `main` publishes the release; see `docs/operations.md`.

## Unreleased

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
