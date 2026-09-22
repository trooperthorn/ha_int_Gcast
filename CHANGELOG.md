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
- `strings.json`: `entity` block and the `request_watchdog` exception.
- Import order follows this repository's ruff configuration.
