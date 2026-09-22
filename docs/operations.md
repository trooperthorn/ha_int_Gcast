# Operations

Configuration options, runtime knobs, logging, and the release procedure.

## Installation

1. Add `https://github.com/trooperthorn/ha_int_Gcast` to HACS as a custom
   repository of type Integration and download it. HACS installs
   `custom_components/cast`, which Home Assistant loads instead of the
   built-in cast integration. Restart Home Assistant.
2. The existing Google Cast config entry keeps working; no re-setup is
   needed. New installs go through the same discovery flow as core.
3. Pin the internal URL to an address (Settings, System, Network, Home
   Assistant URL, internal) before relying on subnet placement; a hostname
   leaves `subnet_mismatch` unknown and a multi-adapter host on Automatic
   raises a repair issue.

To return to core cast, remove the integration in HACS (or delete
`custom_components/cast`) and restart. Entities, devices, and automations
are unchanged; the health sensors become unavailable and can be deleted.

## Options (Settings, Devices and services, Google Cast, Configure)

| Section | Option | Default | Effect |
| --- | --- | --- | --- |
| Known hosts | `known_hosts` | empty | Inherited from core: hosts to poll when mDNS does not work |
| More options | `uuid` | empty | Inherited: allow-list of device uuids |
| More options | `ignore_cec` | empty | Inherited: models whose CEC input state is ignored |
| Delivery health | `probe_enabled` | on | Probe idle audio devices for reachability |
| Delivery health | `probe_interval` | 300 s | Seconds between probe cycles; floor 60 |
| Delivery health | `group_probe_enabled` | on | Also probe speaker groups (off if a group buffers forever, pychromecast #1197) |
| Delivery health | `probe_video_devices` | off | Probe Chromecasts with a display; off because launching an app can wake a TV over CEC |

Option changes apply on the next probe cycle without a reload.

## Constants that are not options

| Constant | Value | Why |
| --- | --- | --- |
| `DELIVERY_TIMEOUT` | 30 s | The window in which a play request must reach BUFFERING, PLAYING, or ERROR before it is `timeout` |
| `REQUEST_WATCHDOG` | 45 s | Cut-off around `quick_play` for user requests; longer than the library's own 30 s so a library `RequestTimeout` is classified first |
| `PROBE_WATCHDOG` | 20 s | Cut-off around `quick_play` for probes |
| `CIRCUIT_BREAKER_TIMEOUTS` | 2 | Consecutive probe timeouts before a device is skipped |
| `CIRCUIT_BREAKER_MAX_BACKOFF` | 3600 s | Cap on the exponential probe backoff |
| `LEDGER_SIZE` | 50 | Records kept for diagnostics |
| `STALE_DEVICE_DAYS` | 7 | Registry devices unseen this long get a repair issue |

## Entities, events, and actions

- `sensor.<device>_tts_outcome`, `sensor.<device>_last_tts_success` on every
  cast device; `sensor.<group>_leader` on configured groups. All diagnostic.
- Event `cast_delivery_result` for every resolved record.
- Action `cast.announce` (message, engine, language, cache, options) on
  this integration's media players.
- Action `cast.show_lovelace_view`, inherited.
- Blueprint `blueprints/automation/trooperthorn/cast_delivery_alert.yaml`.

## Logging

```yaml
logger:
  logs:
    custom_components.cast: debug
    pychromecast: debug
    casttube: debug
```

Log lines from the fork are one line per decision, `key=value`, prefixed
with `[entity_id name uuid=... host=ip:port]`, and say why a status was
ignored (`content_id mismatch`, `media_session_id unchanged`, `state X is
not BUFFERING or PLAYING`). Delivery outcomes are logged at info (`ok`),
warning (failures), or debug (`unknown`, `skipped_busy`). Repair issues log
`repair issue raised id=...` and `repair issue cleared id=...`. Probe
decisions log `probe skipped: <reason>` at debug and circuit changes at
warning and info. An agent can rebuild the ledger from the debug log alone.

## Storage

`.storage/cast.health` holds `last_seen` and `tracked_since` timestamps per
device uuid for stale device detection. Deleting it resets the seven-day
clocks; nothing else depends on it.

## Development gate

The harness needs Linux (it imports `fcntl`); on this workstation it runs in
WSL:

```bash
wsl -e bash -lc 'cd /mnt/c/Users/sean.LAB/repos/ha_int_Gcast && ~/gcastvenv/bin/ruff check . && ~/gcastvenv/bin/mypy --config-file mypy.ini custom_components/cast && ~/gcastvenv/bin/python -m pytest tests -q --cov'
```

`requirements-dev.txt` pins the harness (`pytest-homeassistant-custom-component==0.13.366`,
which brings core 2026.9.3), `PyChromecast==14.0.10`, ruff, mypy with
`homeassistant-stubs`, and the two packages core's `tts` imports at module
load (`mutagen`, `ha-ffmpeg`) because the ported cast tests set `tts` up.

## Releases

Calendar versions `YYYY.MM.DD.N` with no tag prefix. A merge to `main` runs
`test.yml` and `validate.yml` and, when both pass, `release.yml` builds
`cast.zip` deterministically, generates an SPDX SBOM and `SHA256SUMS`,
attests provenance and the SBOM, creates the tag from the merged commit,
and publishes the release. `prepare-release.yml` then opens the next
version bump PR through the release GitHub App when release-bearing paths
changed; without the App variable and secret, bump the version by hand:

```bash
python scripts/set_version.py --next-from-tags
```

and merge the resulting change. `python scripts/build_release_artifacts.py --validate-only`
prints the version the manifest declares and fails on drift.

Verification of a published release:

```bash
gh release download <version> -R trooperthorn/ha_int_Gcast -p cast.zip -p SHA256SUMS
sha256sum --check SHA256SUMS --ignore-missing
gh attestation verify cast.zip -R trooperthorn/ha_int_Gcast
```

## Repository visibility

HACS requires a public repository. While the repository is private, the
HACS validation action and CodeQL are skipped (they cannot read a private
repository's contents or run code scanning without Advanced Security), the
two attestation steps of the release are skipped (GitHub does not persist
attestations for user-owned private repositories), auto-merge cannot be
enabled, and secret scanning is unavailable. Making the repository public
turns all of these on with no other change; the release verification
commands then include `gh attestation verify`.

## Hardware addresses and linked devices

Each cast device is registered with a `CONNECTION_NETWORK_MAC` connection
when its hardware address is known. pychromecast never reports one, so the
address is read from the `dhcp` integration, which maps IP to MAC for every
host it has seen. `dhcp` is an `after_dependency`: when it is not loaded, or
when it has not seen the speaker, the device is registered without a
connection and nothing else changes.

The connection makes the device registry treat this device and the device
another integration creates for the same client, typically a UniFi client,
as linked. They are not merged into one device. Home Assistant Core 2026.8
restricted a device to a single config entry and stopped merging devices
across integrations, so each config entry keeps its own device entry; the
`config/device_registry/list_linked_devices` WebSocket command is what
reports the association.

A speaker on a network Home Assistant does not reach will not have an
address. The per-device diagnostics report `mac` as `null` in that case,
alongside `host` and `subnet`, which is enough to tell "no lease seen" from
"wrong subnet".
