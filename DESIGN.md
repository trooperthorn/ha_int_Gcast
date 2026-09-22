# Design

This file owns the entity model, the outcome vocabulary, how failure is
reported to a person, and the decisions that shaped the fork. Upstream
provenance is in `UPSTREAM.md`; verified facts and their sources are in
`RESEARCH.md`; claims that were not looked up are in `unverified.md`.

## 1. Documentation structure

| File | Owns |
| --- | --- |
| `README.md` | What the fork is, install, the entities and actions it adds, links |
| `DESIGN.md` | This file: entity model, vocabulary, UX of failure, decisions |
| `RESEARCH.md` | Every upstream fact the design relies on, with the source read |
| `UPSTREAM.md` | Fork point, inherited versus owned files, sync procedure |
| `THREAT-MODEL.md` | Trust boundaries, who can do what to whom, advisory findings |
| `unverified.md` | Claims not read from a primary source, with a check command |
| `CHANGELOG.md` | Per-release changes and the running list of upstream divergences |
| `docs/troubleshooting.md` | From "the speaker said nothing" to a cause, using only our entities and diagnostics |
| `docs/operations.md` | Options, probe knobs, release procedure, logging |
| `custom_components/cast/quality_scale.yaml` | Rule-by-rule status with reasons |

## 2. The shape of the fork (work order section 2)

**Option A, shadow the `cast` domain.** A HACS download of this repository
places `custom_components/cast`, which Home Assistant loads instead of the
built-in integration. Entity ids, unique ids, device identifiers, the
`cast.show_lovelace_view` action, Zeroconf discovery, and the single config
entry are all unchanged, so nothing in dashboards or automations moves.
Removing the directory returns the instance to core cast, which is the
rollback for every release.

Rejected: a new domain. It would run two discovery stacks against the same
devices, need de-duplication that core does not provide, and force every
automation and dashboard to migrate. The persistent "custom integration"
warning that Option A produces is accurate and the README says so.

**Fork from the stable tag, not `dev`.** `dev` carries the 2026.10
`probatio` migration that does not import on the 2026.9 instance this fork
runs on. See `UPSTREAM.md`.

## 3. Outcome vocabulary

Closed set, stored on `sensor.<device>_tts_outcome` (device class `enum`)
and carried by every `cast_delivery_result` event.

| Value | Meaning | Evidence that produces it |
| --- | --- | --- |
| `ok` | The device acknowledged the request and entered BUFFERING or PLAYING for the content id we asked for, in a new media session | A `MediaStatus` callback with matching `content_id`, `player_state` in (BUFFERING, PLAYING), and `media_session_id` different from the one recorded when the request was sent |
| `fetch_failed` | Cast accepted the command; the device could not retrieve or decode the media, or rejected the app launch. The 2026-09-21 case | `player_is_idle` with `idle_reason == "ERROR"` for the requested content id (or with no content id), a `LOAD_FAILED` message, `RequestFailed` while connected (pychromecast raises it for a `LAUNCH_ERROR` answer too; the receiver's last `LaunchFailure` reason goes into the error text), or a non-transport `PyChromecastError` |
| `unreachable` | No Cast channel to the device on port 8009 | `NotConnected`, `ChromecastConnectionError`, `RequestFailed` while the entity is unavailable, or a probe cycle finding the entity unavailable |
| `timeout` | Nothing happened inside the window. The outcome is genuinely unknown and must not be reported as success | No qualifying status within `DELIVERY_TIMEOUT` (30 s) after the request, a `RequestTimeout` from the library, or the `REQUEST_WATCHDOG` (45 s) cutting a `quick_play` that never returned |
| `template_error` | A message or data template failed to render, so no TTS was ever requested | The `cast.announce` action (WP4) catching `TemplateError` |
| `skipped_busy` | A probe was due but the device was not idle, so it was not interrupted | WP2 coordinator |
| `unknown` | No evidence yet, or a request was superseded before any evidence arrived | Entity creation; a second play request replacing an unresolved first one |

`skipped_busy` and `unknown` never overwrite the sensor's last real outcome;
they appear in the ledger and the event stream only. A healthy device with
probing enabled cannot rest at `unknown` for longer than one probe interval.

## 4. Entity model

Every discovered non-dynamic-group cast device gets, on the same device
record as its media player:

| Entity | Class | State | Attributes |
| --- | --- | --- | --- |
| `sensor.<device>_tts_outcome` | enum, diagnostic | last outcome | `source` (`play_media`, `probe`, `announce`, `observed`), `content_id`, `url_source` (`internal_url`, `external_url`, or none), `error`, `responded`, `elapsed`, `player_state`, `idle_reason`, `checked_at`, `consecutive_failures`, `consecutive_timeouts`, `circuit_open`, `subnet_mismatch`, `host`, `port` |
| `sensor.<device>_last_tts_success` | timestamp, diagnostic | when a delivery last resolved `ok`; restored across restarts | none |

Groups (WP3) add `sensor.<group>_leader`.

Event `cast_delivery_result` carries the full record: `uuid`, `entity_id`,
`name`, `source`, `outcome`, `content_id`, `error`, `url_source`,
`responded`, `requested_at`, `resolved_at`, `elapsed`, `player_state`,
`idle_reason`, `media_session_id`. It fires for every resolved record
including probes, so an automation can alert on `outcome != ok` without
polling the sensor.

`responded` separates "the device answered with a failure" (the 2026-09-21
incident) from "the device said nothing" (pychromecast #1247). Both are
failures; they point at different causes.

## 5. Keying and evidence rules

pychromecast #1018: `MediaStatus.update()` copies only the keys present in
each message and never clears `content_id` or metadata, so a status can
carry the previous track's content id long after it stopped. The ledger
therefore:

1. Keys every pending request on the content id this integration asked
   for, never on what the status reports.
2. Requires a **changed** `media_session_id` before `ok`. A status with the
   requested content id but the session id recorded at request time is stale
   metadata and is ignored. This also covers a TTS cache hit, where the same
   URL is re-announced while its previous session is still current.
3. Treats an `ERROR` idle status for a different content id as an observed
   failure (recorded, event fired) without resolving the pending request.
4. Records a superseded request as `unknown`, not as a failure and not as
   success.

The only case where the rule set knowingly loses evidence: a device that
reports BUFFERING for our content id while keeping the old session id
(no firmware observed doing this; it would surface as `timeout`, never as a
false `ok`, which is the safe direction).

## 6. Threading

pychromecast delivers `new_media_status`, `load_media_failed`, and connection
callbacks on its socket client thread. The entity extracts plain values
(content id, player state, idle reason, session id) and hands them to the
event loop with `loop.call_soon_threadsafe`; the ledger, sensors, event bus,
and issue registry are touched only on the loop. Nothing in the fork shares
the mutable `MediaStatus` object across threads, and `CastStatusListener`'s
invalidation discipline is untouched.

## 7. Watchdogs (pychromecast #1247)

Every call into `quick_play` runs in the executor under
`asyncio.timeout(REQUEST_WATCHDOG)`. The library's own 30 s wait is not
trusted because #1247 shows `launch_app` hanging with the heartbeat alive. A
watchdog expiry records `timeout` with `responded=false` and raises a
translated `HomeAssistantError` so the calling automation sees the failure.
The executor thread is not killed (Python cannot), so a truly wedged call
holds one executor slot until the library gives up; the circuit breaker in
WP2 stops the probe from repeating that.

## 8. Failure reporting UX

- Sensor states use the vocabulary words; the translated display names are
  "OK", "Fetch failed", "Unreachable", "Timeout", "Template error",
  "Skipped, busy", "Unknown".
- Every warning log line and every repair issue names the device, the URL
  source that was used, and the next action. Wording is in
  `strings.json`; the troubleshooting guide expands each outcome.
- Debug logging is structured `key=value` on one line per decision,
  prefixed `[entity_id name uuid=... host=...]`, and states why a status was
  ignored (content id mismatch, session unchanged, state not a transition),
  so an agent reading the log can reconstruct the state machine without the
  source.

## 9. Active probing (WP2)

A `DataUpdateCoordinator` runs every `probe_interval` seconds (default 300,
floor 60, set in the integration options under "Delivery health"). The
refresh itself never waits on a device: for each registered media player it
takes a snapshot on the event loop, decides, and either records the decision
or launches the probe as a background task. A wedged device therefore delays
neither the refresh nor any other device's probe.

The probe plays a quarter second of 8 kHz silence served by this Home
Assistant instance at `/api/cast/probe/<token>.wav` through the default
media receiver, using the same base URL selection as TTS playback
(`get_url(hass)`) and, like the TTS proxy, no request signature. The outcome
is judged by exactly the same ledger rules as a real announcement, so a
probe `ok` means "this device fetched audio from this instance's URL just
now". The token is random per Home Assistant start; the view is
unauthenticated for the same reason the TTS proxy is (cast devices cannot
present credentials).

Decision order per device:

| Condition | Decision | Recorded as |
| --- | --- | --- |
| Previous probe still running | skip | debug log only |
| Entity unavailable or not connected | skip | debug log only |
| Audio group and group probing off | skip | debug log only |
| Video device (`cast_type == "cast"`) and video probing off (default) | skip; launching an app on a Chromecast with a display can wake the TV over CEC | debug log only |
| Circuit open and backoff not elapsed | skip | debug log with remaining seconds |
| Own `player_state` or any group's state in PLAYING, BUFFERING, PAUSED | `skipped_busy` | ledger record and event; the sensor keeps its last real outcome |
| Otherwise | probe | ledger `source=probe` |

Guards, all driven by pychromecast #1247:

1. `quick_play` runs in the executor under `asyncio.timeout(PROBE_WATCHDOG)`
   (20 s). The library's own 30 s wait is not relied on.
2. The state transition wait is the ledger's 30 s timer, so "no response at
   all" (`timeout`, `responded=false`) is distinct from "responded with a
   failure" (`fetch_failed`, `responded=true`).
3. Circuit breaker per device: after `CIRCUIT_BREAKER_TIMEOUTS` (2)
   consecutive probe timeouts the device is skipped for
   `interval * 2^(n-1)` seconds, capped at one hour, then probed once
   (half-open). An `ok` closes the circuit and resets the counters; another
   timeout doubles the backoff. Real playback requests are never blocked by
   the breaker; only probes are.
4. After a successful probe on a device whose app was idle beforehand, the
   media receiver is quit so the device returns to the state it was in.
   Failure to quit is logged at debug and does not change the outcome.

Group probing is a separate option (`group_probe_enabled`) because of
pychromecast #1197 (groups that buffer forever on play).

## 10. Topology and subnet awareness (WP3)

A speaker group's `_googlecast._tcp` record is advertised from the leader's
IP on a dynamic high port instead of 8009, so the group's own
`ChromecastInfo.cast_info.host` and `port` are the leader address. Members
come from pychromecast's `MultizoneManager` (`get_multizone_memberships` per
device, inverted). The device setup endpoint is not consulted: on firmware
`1.56.467166` it returns no `multizone` key (work order, verified twice on
2026-09-22).

`sensor.<group>_leader` (diagnostic) on every configured group device:

| Field | Meaning |
| --- | --- |
| state | `leader_ip` |
| `leader_uuid` | The non-group device whose discovery host equals the leader IP, or none if the leader is not a discovered device |
| `advertised_port` | The dynamic port from the group record |
| `member_uuids`, `member_ips` | From the multizone manager; empty until the members have connected |
| `subnets` | The adapter network containing each address, or an assumed /24 when no adapter matches |
| `members_span_subnets` | True when leader and members resolve to more than one subnet; None when nothing could be placed |
| `is_dynamic_group` | Always false on the sensor; dynamic groups have no entity and appear in diagnostics with the flag set |

A leader move is logged at info (`leader moved from a:port to b:port`) and
the sensor updates on the next topology refresh, which runs on every probe
cycle and can be forced by a config entry reload.

Subnet placement of every device (`subnet_mismatch` on the outcome sensor):
the `internal_url` host is resolved to an IPv4 literal, matched against the
enabled adapters' IPv4 networks (falling back to an assumed /24), and each
device IP is tested against those "home" networks. A hostname `internal_url`
leaves placement unknown (`null`) rather than guessed, which is one more
reason to pin `internal_url` to an address (work order open question 5). A
mismatch with a working probe is not a failure: the outcome stays `ok` and
only the attribute is set, so the sensor is never trained to be ignored.

## 11. Diagnostics, repairs, and registry hygiene (WP4)

### Repair issues

| Issue id | Severity | Raised when | Clears when |
| --- | --- | --- | --- |
| `tts_fetch_failed.<uuid>` | error | Two consecutive `fetch_failed` outcomes for a device (any source) | The next `ok` for that device |
| `internal_url_automatic_multihomed` | warning | Two or more enabled adapters carry IPv4 and `internal_url` is on Automatic | Either condition clears on the next topology refresh |
| `cast_group_spans_subnets.<uuid>` | warning | A group's leader and members resolve to more than one subnet | The members share a subnet |
| `stale_cast_device.<device_id>` | warning, fixable | A registry device of this entry has had no discovery response for 7 days (from its last sighting, or from when the fork first saw the registry entry) | The device is discovered again, or the repair removes it |
| `tts_template_error.<sha1[:12]>` | error | A `cast.announce` message template raised `TemplateError` or rendered empty | The same template renders successfully |

Every issue names the device or group and states the next action in its
description; none needs manual dismissal. Issue transitions are logged
(`repair issue raised id=... key=value ...`, `repair issue cleared id=...`)
so an agent can correlate them with the ledger lines.

### Stale device tracking

Discovery timestamps per device uuid are persisted in `.storage/cast.health`
(`last_seen`, `tracked_since`), restored into the ledger on setup, and
flushed on unload. The stale check runs on every probe cycle, even with
probing disabled. The fix flow deletes the registry device after a
confirmation form that names it.

### The monitored announce action

`cast.announce` (target: this integration's media players; fields:
`message`, `engine`, `language`, `cache`, `options`) renders the message
template itself, so a template failure becomes a `template_error` outcome,
an event, and a repair issue, instead of an automation trace. Because the
automation engine renders templates in action data before the call, an
automation must wrap the template in `{% raw %} ... {% endraw %}` for it to
reach the action unrendered; a plain string is announced as is and still
tracked with `source=announce`. An unavailable TTS engine is also recorded as
`template_error` with the engine error as the reason, since no announcement
was requested.

### Diagnostics

The download carries: the resolved internal and external URLs with whether
each is pinned and which adapter network the internal host sits on
(external host redacted); every discovered device with name, model, host,
subnet, last outcome, last success, last seen, consecutive failures, and
circuit state; every group with leader and membership; the last 50 ledger
records; registry devices with no matching discovered device; probe options
and the last decision per device; active issue ids and stale candidates.
`user_id` and the external URL are redacted.

## 12. Decisions

| Date | Decision | Alternative rejected |
| --- | --- | --- |
| 2026-09-22 | Option A, shadow `cast` | New domain: discovery de-duplication, entity migration |
| 2026-09-22 | Fork from tag `2026.9.2` | `dev`: needs `probatio`, unavailable on 2026.9 |
| 2026-09-22 | Ruff sorts imports per this repository's config | Keeping core's import order verbatim: would need a ruff exclusion for inherited files; the diff against core is import order only and is mechanical to reapply |
| 2026-09-22 | Strict mypy on inherited files, with `type: ignore[override]` where core's own signatures disagree with `MediaPlayerEntity` (`media_duration`, `media_position` are floats; `media_season`, `media_episode` are ints from the library) | Coercing values to the base class types: changes state attributes users already have |
| 2026-09-22 | Add `async_unload_entry` (core cast has none) | Leaving options changes to require a restart |
| 2026-09-22 | `ok` requires a changed media session id | Content id match alone: defeated by #1018 and TTS cache hits |
| 2026-09-22 | The health sensors hang off the discovery signal, one pair per device, and never for dynamic groups | Creating them from the media player entity: couples two platforms |
| 2026-09-22 | A superseded request resolves as `unknown` | `timeout`: would count as a failure and open the circuit breaker for a device that was merely asked twice |
