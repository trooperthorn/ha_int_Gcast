# Research

Every fact the design relies on, with the primary source it was read from.
"Read" means the file was opened in this repository's toolchain on the date
given; nothing here is recalled from memory. Claims that could not be
verified are in `unverified.md`.

Sources used: the core clone at tag `2026.9.2`
(`~/repos/ha-core-reference`), the installed `PyChromecast==14.0.10` package,
the developer documentation clone, and the GitHub API.

## WP0

| Fact | Source | Date |
| --- | --- | --- |
| Core cast at `2026.9.2` is 2035 lines across seven Python files; `dev` differs only by the `voluptuous` to `probatio` migration in `config_flow.py` and `home_assistant_cast.py` | blob hashes from the GitHub contents API versus `git hash-object` | 2026-09-22 |
| Core manifest: `requirements` `PyChromecast==14.0.10`, `loggers` `casttube`, `pychromecast`, `after_dependencies` `cloud`, `http`, `media_source`, `plex`, `tts`, `zeroconf`, `single_config_entry` true, `iot_class` `local_polling`, `integration_type` `hub`, no `quality_scale` | `homeassistant/components/cast/manifest.json` | 2026-09-22 |
| Core cast declares no `async_unload_entry` | `homeassistant/components/cast/__init__.py` | 2026-09-22 |
| Core cast's 88 tests pass against the ported copy on the harness (`pytest-homeassistant-custom-component==0.13.365`, core 2026.9.2, Python 3.14.4) | test run in the WSL venv | 2026-09-22 |
| Core's `tts` component imports `mutagen` and `ha-ffmpeg` at module import, so the ported tests need both | `homeassistant/components/tts/__init__.py`, `package_constraints.txt` (`mutagen==1.48.1`, `ha-ffmpeg==3.2.2`) | 2026-09-22 |
| Strict mypy reports 99 errors on the unmodified core files (untyped callbacks and properties) | mypy 2.3.1 with `homeassistant-stubs==2026.9.2` | 2026-09-22 |

## WP1

### The failure signal

| Fact | Source | Date |
| --- | --- | --- |
| The error originates in `new_media_status()` gated on `media_status.player_is_idle and media_status.idle_reason == "ERROR"`, compares `content_id` against `get_url(hass, allow_internal=False)` and `get_url(hass, allow_external=False)`, calls `_LOGGER.error`, and writes no state, event, or attribute | `media_player.py` lines 401 to 439 at the fork point | 2026-09-22 |
| `MediaStatus.update()` copies `contentId`, `contentType`, `duration`, `streamType`, `mediaSessionId`, `playerState`, and `metadata` only when present in the message; `idleReason` is the one field cleared when absent | `pychromecast/controllers/media.py` lines 307 to 340 | 2026-09-22 |
| pychromecast defines no enumeration of idle reasons; `idle_reason` is whatever string the device sends | grep of the installed package: the only `idleReason` reference is the `update()` line | 2026-09-22 |
| `player_is_idle`, `player_is_playing`, `player_is_paused` are properties on `MediaStatus` derived from `player_state` | `pychromecast/controllers/media.py` lines 160 to 190 | 2026-09-22 |
| Callbacks fire on the socket client thread: `SocketClient` subclasses `threading.Thread`; `_fire_status_changed` iterates listeners and calls `new_media_status(self.status)` with the controller's single mutable `MediaStatus` object | `pychromecast/socket_client.py` line 138, `controllers/media.py` lines 760 to 775 | 2026-09-22 |
| `load_media_failed(queue_item_id, error_code)` fires on a `LOAD_FAILED` message when both `itemId` and `detailedErrorCode` are present; the codes are the receiver error codes 100 to 431 | `controllers/media.py` lines 80 to 108 and 741 to 757 | 2026-09-22 |
| Core's `CastStatusListener` forwards `new_cast_status`, `new_media_status`, `load_media_failed`, `new_connection_status`, `multizone_new_media_status`, and `removed_from_multizone` only while `_valid`; `invalidate()` deregisters from the multizone manager first | `helpers.py` lines 160 to 240 | 2026-09-22 |

### Request path and timeouts

| Fact | Source | Date |
| --- | --- | --- |
| `quick_play(cast, app_name, data, timeout=30.0)` picks a controller by app name; `default_media_receiver` maps to `DefaultMediaReceiverController.quick_play`, which calls `play_media(..., callback_function=WaitResponse.callback)` and blocks on `wait_response()` | `pychromecast/quick_play.py`, `controllers/media.py` lines 550 to 560 | 2026-09-22 |
| `WaitResponse.wait_response()` raises `RequestTimeout` when the event is not set within `timeout`, and `RequestFailed` when the message was not sent | `pychromecast/response_handler.py` lines 32 to 57 | 2026-09-22 |
| `Chromecast.start_app`, `quit_app`, `set_volume` use `WaitResponse(REQUEST_TIMEOUT, ...)`; `wait()` raises `RequestTimeout` | `pychromecast/__init__.py` lines 442 to 505 | 2026-09-22 |
| `ReceiverController.launch_app` sends the launch message through `_send_launch_message` with a callback; the blocking wait lives in the caller, and the callback is the only completion signal (the mechanism #1247 reports never firing) | `controllers/receiver.py` lines 153 to 200 | 2026-09-22 |
| Exception classes: `PyChromecastError` base; `ChromecastConnectionError`, `NotConnected`, `RequestFailed`, `RequestTimeout` | `pychromecast/error.py` | 2026-09-22 |
| Core wraps every pychromecast call in `api_error`, which re-raises `PyChromecastError` as `HomeAssistantError` with the original as `__cause__`; the fork classifies by that cause | `media_player.py` lines 94 to 111 | 2026-09-22 |
| `asyncio.timeout` re-raises the inner `CancelledError` as `TimeoutError` with the `CancelledError` as `__cause__`, so the ledger must not describe a watchdog expiry by its cause | Python 3.14 `asyncio.timeouts`, observed in `test_hung_play_request_hits_watchdog` | 2026-09-22 |

### Home Assistant APIs used

| Identifier | Verified in | Date |
| --- | --- | --- |
| `homeassistant.helpers.network.get_url(hass, *, allow_internal, allow_external, ...)` and `NoURLAvailableError` | `helpers/network.py` line 115 | 2026-09-22 |
| `RestoreSensor.async_get_last_sensor_data()` returning `SensorExtraStoredData` with `native_value` | `components/sensor/__init__.py` lines 973 to 1040 | 2026-09-22 |
| `SensorDeviceClass.ENUM` with `_attr_options`, `SensorDeviceClass.TIMESTAMP` | `components/sensor/const.py`, `__init__.py` line 200 | 2026-09-22 |
| `hass.bus.async_fire(event_type, event_data)` | `core.py` line 1567 | 2026-09-22 |
| `async_call_later(hass, delay, action)` returning a cancel callable | `helpers/event.py` line 1552 | 2026-09-22 |
| `HomeAssistant.async_block_till_done` starts with `await asyncio.sleep(0)` to flush `call_soon_threadsafe` callbacks, which is why the tests need no extra yield after invoking a socket-thread callback on the loop | `core.py` line 997 | 2026-09-22 |
| `hass.config_entries.async_unload_platforms`, `entry.async_on_unload` | `config_entries.py` | 2026-09-22 |
| `async_get_integration(hass, domain).is_built_in`, `file_path` | `loader.py` lines 275, 779 | 2026-09-22 |

### Library maintenance state

| Fact | Source | Date |
| --- | --- | --- |
| `14.0.10` published 2026-03-07, still latest; 72 commits since on `master`; library code touched only by `63064b6` (reconnect guard, #1242) and `8e29f99` (Bravia models); `eb2a9ff` adds `AI_POLICY.md` | GitHub API `compare/14.0.10...master`, `releases/latest` | 2026-09-22 |
| The work order's "released 2025-03-07, roughly 18 months old" is off by a year; the conclusion (no release with the reconnect fix) stands | same | 2026-09-22 |

## WP2

| Fact | Source | Date |
| --- | --- | --- |
| TTS playback resolves to the relative path `/api/tts_proxy/<token>` (`ResultStream.url`), which `async_process_play_media_url` turns absolute with `get_url(hass)`; `/api/tts_proxy/` is in `PATHS_WITHOUT_AUTH`, so the URL is not signed | `components/tts/__init__.py` line 520, `components/media_player/browse_media.py` lines 34 to 85 | 2026-09-22 |
| A relative path outside `PATHS_WITHOUT_AUTH` is signed (`authSig` query) and core notes some devices reject long URLs; the probe therefore builds its URL with `get_url(hass)` directly | same file, lines 59 to 70 | 2026-09-22 |
| `Chromecast.is_idle` is true when there is no status, the app is `IDLE_APP_ID` (`E8C28D3C`) or none, or a Chromecast's active input is off | `pychromecast/__init__.py` lines 367 to 377 | 2026-09-22 |
| `DataUpdateCoordinator` polls only while it has listeners; `update_interval` has a setter; `hass.async_create_background_task(..., eager_start=True)` exists | `helpers/update_coordinator.py` lines 242 to 250, `core.py` line 839 | 2026-09-22 |
| `HomeAssistantView` supports `requires_auth = False`; `hass.http.register_view` registers once per instance | `helpers/http.py` line 126, `components/http/__init__.py` | 2026-09-22 |
| The harness's `hass_client_no_auth` fixture exercises an unauthenticated view | `pytest_homeassistant_custom_component/plugins.py` | 2026-09-22 |
| `MockConfigEntry(options=...)` plus `hass.config_entries.async_update_entry(entry, options=...)` triggers update listeners; an options flow's `async_create_entry(data=...)` replaces `entry.options` with `data`, so the flow must return the merged options or the values are lost | observed in `test_option_flow_health_section`; `config_entries.py` `async_update_entry` | 2026-09-22 |
| A probe against a device blocked at the firewall cannot be exercised in the harness; the closest reproduction is the `ERROR` idle status the device sends in that case | work order section 4.1 and `test_probe_mdns_visible_but_unreachable` | 2026-09-22 |

## WP3

| Fact | Source | Date |
| --- | --- | --- |
| `MultizoneManager` keeps `_casts[member_uuid]["group_memberships"]` and exposes `get_multizone_memberships(member_uuid) -> list[str]` (raises `KeyError` for a device it has not seen) and `get_multizone_mediacontroller(group_uuid)`; it has no group-to-members accessor, so the fork inverts the memberships | `pychromecast/controllers/multizone.py` lines 176 to 230 | 2026-09-22 |
| Core registers each non-group entity with the manager in `CastStatusListener.__init__` and adds each group with `add_multizone`; `invalidate()` reverses both | `helpers.py` lines 173 to 240 | 2026-09-22 |
| Core's `CastInfo` for a group carries the leader host and the dynamic port; `ChromecastInfo.is_dynamic_group` is filled from `dial.get_multizone_status` during discovery | `helpers.py` lines 60 to 130, `pychromecast/dial.py` lines 296 to 335 | 2026-09-22 |
| `network.async_get_adapters(hass)` returns `Adapter` dicts with `enabled`, `ipv4: [{address, network_prefix}]`; the harness `mock_network` fixture provides one adapter `10.10.10.10/24` | `components/network/__init__.py` line 42, `models.py` lines 15 to 31, harness `plugins.py` line 1342 | 2026-09-22 |
| `hass.config.internal_url` is `None` when the URL is on Automatic | `core_config.py` line 557 | 2026-09-22 |
| Core's test helper `async_setup_media_player_cast` restricts the entry to the one wanted uuid and its inner `discover_chromecast` subscripted a dataclass (`FAKE_MDNS_SERVICE[1]`), which raises `TypeError`; the vendored copy takes `wanted_uuids` and uses `.name` | `tests/components/cast/test_media_player.py` lines 215 to 283 at the fork point | 2026-09-22 |

## Corrections to the work order

- Section 4.4: release date is 2026-03-07, not 2025-03-07.
- Section 4.2 is confirmed as written.
- Section 6 layout: `quality_scale.yaml` and `translations/en.json` are
  present; `health.py`, `coordinator.py`, `probe.py`, `topology.py`,
  `repairs.py`, and `sensor.py` are additions the layout did not list.
