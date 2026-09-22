# Threat model

Scope: the `cast` custom integration as shipped by this repository, running
inside a Home Assistant instance on a home network. Findings marked
"advisory" describe exposure the fork inherits or accepts and does not
change; they are recorded so nobody mistakes them for oversights.

## 1. Trust boundaries

| Boundary | What crosses it | Direction | Trust |
| --- | --- | --- | --- |
| Local network to the integration | mDNS `_googlecast._tcp` records (name, uuid, model, host, port); HTTP `eureka_info` responses on port 8008; Cast channel messages on port 8009 (media status, connection status, group membership) | inbound | untrusted: any host on the multicast domain can advertise a record or answer on 8008/8009 |
| The integration to devices | `LOAD` requests carrying a media URL; `quit_app`; probe playback | outbound | the device is trusted to play what it is told, nothing more |
| Devices to the Home Assistant HTTP server | Fetches of `/api/tts_proxy/<token>` and `/api/cast/probe/<token>.wav`, both unauthenticated by design | inbound | untrusted clients, opaque tokens |
| The integration to the Home Assistant state machine, event bus, issue registry, device registry, `.storage/cast.health` | Sensor states and attributes, `cast_delivery_result` events, repair issues, device removal through the repair flow, discovery timestamps | internal | trusted process; anything else in the same Python process can do the same |
| Home Assistant Cast (inherited) | The `cast.show_lovelace_view` action sends the Home Assistant Cast system user's refresh token to a device over the Cast channel | outbound | the device and its network path see an admin-scoped token |

## 2. Assets

- The Home Assistant Cast system user's refresh token (inherited from core;
  admin group).
- The truthfulness of the delivery outcome sensors and events. The purpose
  of the fork is that these are believed; a false `ok` is the primary harm.
- Availability of the event loop and executor (a wedged probe must not take
  the instance down).
- The device registry (the stale device repair deletes entries).

## 3. Who can do what to whom

| Actor | Capability | Effect on this integration | Mitigation |
| --- | --- | --- | --- |
| A host on the local multicast domain | Advertise a fake `_googlecast._tcp` record | A device entity, health sensors, and (if it claims group type) a leader sensor are created for it; the probe will try to play the clip to it; the topology may record it as a group leader | Identical exposure to core cast. Entities carry the advertised name only after discovery filled it in; `known_hosts` and the `uuid` allow-list in the options restrict which devices are accepted. Advisory. |
| The same host | Answer on 8009 with crafted media status messages | Can drive the outcome sensor for its own entity to any value, including `ok`, and fire events | Outcomes are per device; a rogue device cannot change another device's outcome because the ledger keys on the entity's own socket. The `media_session_id` rule prevents a replayed old status from confirming a new request. Advisory. |
| The same host | Answer `eureka_info` with `dynamic_groups` | Marks a uuid as a dynamic group, suppressing its entity | Inherited from core cast. Advisory. |
| Any client that can reach the Home Assistant HTTP port | Fetch `/api/cast/probe/<token>.wav` by guessing the token | Downloads a quarter second of silence | Token is 16 random bytes per start, compared in constant time; the payload has no value. Not a finding. |
| Any client that can reach the HTTP port | Hammer the probe view | Serves 2 KB responses from memory | No disk, no template, no state; bounded by the aiohttp server as any other view. Not a finding. |
| A device that never answers (pychromecast #1247) | Hold an executor thread | One executor slot per wedged call until the library gives up (`quick_play` 30 s, connection timeouts) | Every call runs behind an `asyncio.timeout`; the probe circuit breaker stops repeats; playback requests are user-initiated. Residual: a device that wedges every `quick_play` costs one executor slot per user request for up to 30 s each. Advisory. |
| A Home Assistant user with automation rights | Call `cast.announce` with a template | Renders in the server template sandbox, exactly as `tts.speak` data would have | Same trust as any template-accepting action. Not a finding. |
| A Home Assistant admin | Submit the stale device repair | Deletes a device registry entry | Requires confirmation; the entry is recreated on next discovery if the device still exists. Not a finding. |
| Anyone reading a diagnostics download | Learn device names, local IPs, subnets, and the internal URL | Local-only topology | External URL and the Cast user id are redacted; local addresses are needed for the diagnosis to be useful and the download is admin-only. Accepted. |
| Anyone reading the logs | Learn media URLs including TTS proxy tokens | Tokens are short-lived (TTS cache) and unauthenticated by design | Inherited from core, which logs the same URL at error level; the fork adds them at warning and debug level. Advisory. |

## 4. What the fork changes about the attack surface

- Adds one unauthenticated HTTP route (`/api/cast/probe/<token>.wav`),
  static content, random token, constant-time comparison.
- Adds periodic outbound `LOAD` requests to idle audio devices (probing),
  never to video devices unless enabled, never to busy devices.
- Adds `.storage/cast.health` (discovery timestamps only).
- Adds state, events, and issues; none of them carry the Cast refresh token.
- Does not change the Cast channel handling, the multizone listener, the
  Home Assistant Cast controller, or the config flow's accepted inputs.

## 5. Advisory findings inherited from core cast

1. The Home Assistant Cast refresh token is admin-scoped and is sent to
   whatever device is asked to show a dashboard. A rogue device on the
   network that is asked to show a view receives an admin token. Out of
   scope for this fork; documented so operators do not cast dashboards to
   untrusted devices.
2. `_fetch_playlist` in `helpers.py` fetches user-supplied playlist URLs
   with `verify_ssl=False`. Inherited; unchanged to keep upstream parity.
3. Discovery accepts any mDNS record. Inherited; `known_hosts` and the
   `uuid` allow-list are the controls.

## 6. Tests that prove the properties

| Property | Test |
| --- | --- |
| A failed fetch is never reported as `ok` | `test_mdns_visible_but_unreachable`, `test_probe_mdns_visible_but_unreachable` |
| A timeout is never reported as `ok` and leaves `last_tts_success` untouched | `test_timeout_not_recorded_as_success` |
| Stale metadata cannot confirm a request | `test_stale_metadata_not_treated_as_confirmation` |
| A wedged device does not stall the refresh or its peers | `test_hung_device_does_not_block_others` |
| Repeated wedges stop being probed | `test_circuit_breaker_opens`, `test_circuit_backoff_grows_and_caps` |
| The probe view serves only the current token | `test_probe_view_serves_silence` |
| Diagnostics redact the external URL and user id | `test_diagnostics_answer_is_tts_working` |
| Device removal needs confirmation and an existing issue | `test_stale_device_issue_and_fix_flow` |
