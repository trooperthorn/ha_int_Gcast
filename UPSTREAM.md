# Upstream provenance and sync strategy

This repository is a fork of the Home Assistant core `cast` integration. It
keeps the `cast` domain so a HACS download replaces the built-in copy in place
(entity ids, unique ids, devices, actions, and discovery are unchanged) and
uninstalling returns the user to core. That decision is Option A of the work
order; the reasoning is in `DESIGN.md`.

## Fork point

| Item | Value |
| --- | --- |
| Upstream repository | `home-assistant/core` |
| Upstream path | `homeassistant/components/cast` |
| Fork commit | `33c3e0cca60e73a8c4970ee677d75b8bc6464cdf` (tag `2026.9.2`) |
| Fork date | 2026-09-22 |
| Library pin carried forward | `PyChromecast==14.0.10` (exact, as core pins it) |

The work order named `dev` as the upstream reference. The fork is taken from
the `2026.9.2` tag instead, because the test harness and the target instance
run 2026.9.x and `dev` already carries the 2026.10 migration from
`voluptuous` to `probatio` (core commit `14f9b7e699d6`, 2026-09-13), which
does not import on 2026.9. On 2026-09-22 that migration was the only
difference between `dev` and the tag in this directory (`config_flow.py` and
`home_assistant_cast.py`; every other file had an identical blob hash).

## Which files are ours and which are inherited

| File | Status |
| --- | --- |
| `__init__.py`, `config_flow.py`, `const.py`, `discovery.py`, `helpers.py`, `home_assistant_cast.py`, `media_player.py`, `services.yaml`, `icons.json`, `strings.json` | Inherited. Edited only where a work package needs a hook; every edit is listed in `CHANGELOG.md` under "Divergence from upstream". |
| `manifest.json` | Inherited keys preserved; `codeowners`, `documentation`, `issue_tracker`, and `version` are ours. |
| `health.py`, `coordinator.py`, `sensor.py`, `diagnostics.py`, `repairs.py`, `topology.py`, `probe.py`, `quality_scale.yaml`, `translations/` | Ours. |
| `tests/` | Core's tests ported to the harness (recipe below) plus our own. |

## Sync cadence and procedure

1. On the first weekday after each monthly core release, compare
   `homeassistant/components/cast` at the new stable tag against the fork
   point recorded above:

   ```bash
   gh api "repos/home-assistant/core/contents/homeassistant/components/cast?ref=<tag>" --jq '.[] | "\(.sha) \(.name)"'
   ```

   and compare the blob hashes with `git hash-object` on the local copies.
2. For each changed inherited file, apply the upstream diff on a branch,
   rerun the full gate, and record the reconciliation in `CHANGELOG.md` with
   the upstream commit. If an upstream change conflicts with a fork hook,
   the fork hook moves; upstream behavior wins for everything the hook does
   not own.
3. Update the fork point table and the hacs.json `homeassistant` floor.
4. A missed reconciliation reverts nothing (the custom component keeps
   shadowing core), but it withholds upstream fixes; the weekly validate
   workflow does not detect this, so the calendar entry is the control.

## Porting core tests to the harness

`tests.common`, `tests.typing`, and `tests.test_util.aiohttp` become the
`pytest_homeassistant_custom_component` modules of the same name;
`homeassistant.components.cast` becomes `custom_components.cast` in imports
and patch targets; `async_load_fixture(hass, name, DOMAIN)` becomes
`load_fixture(name)` because the harness resolves `tests/fixtures` from the
calling test file and the async variant resolves from an executor thread;
`tests.components.media_player.common` is vendored as
`tests/media_player_common.py`; the `mock_tts_cache_dir` fixture family and
the `media` directory that core keeps under `tests/testing_config` live in
`tests/conftest.py` and `tests/fixtures/media`; the cloud fallback test stubs
`homeassistant.components.cloud` in `sys.modules` because the harness does
not install `hass-nabucasa`.

## pychromecast state at fork time

Verified with the GitHub API on 2026-09-22:

| Fact | Value |
| --- | --- |
| Latest release | `14.0.10`, published 2026-03-07 |
| Commits on `master` since the tag | 72, touching 9 files |
| Library code commits | `63064b6` (2026-07-12, `socket_client.py`, reconnect loop guard, #1242) and `8e29f99` (2026-07-12, `const.py`, two Bravia models, #1207) |
| Other non-dependabot commit | `eb2a9ff` (2026-07-21, `AI_POLICY.md`) |

The work order dated the release 2025-03-07; the API says 2026-03-07, so the
release is about six months old, not eighteen. The conclusion does not
change: the reconnect fix is unreleased and the fork must not depend on a
library release appearing.
