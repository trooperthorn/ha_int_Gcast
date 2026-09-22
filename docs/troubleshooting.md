# Troubleshooting: the speaker said nothing

This guide goes from "an announcement was not heard" to a specific cause
using only the entities, events, repair issues, and diagnostics this
integration provides. No log reading is required; every step names what to
open and what to look for.

## Step 1: read the outcome sensor

Open the device page of the speaker and look at **TTS outcome**
(`sensor.<device>_tts_outcome`). Its state is the last verdict; its
attributes are the evidence. `checked_at` says when the verdict was reached
and `source` says what produced it (`play_media` for an announcement,
`probe` for a background check, `announce` for the `cast.announce` action,
`observed` for a failure the device reported on its own).

| State | Meaning | Go to |
| --- | --- | --- |
| `ok` | The last delivery was acknowledged and started playing. If nothing was heard, the audio path after the device is the problem (volume, mute, the group the device belongs to). | Step 6 |
| `fetch_failed` | The device accepted the command and then could not fetch the audio from Home Assistant. This is the case where the speaker is visible but Home Assistant is not reachable from the speaker's network. | Step 2 |
| `unreachable` | Home Assistant had no Cast channel to the device on port 8009 when it tried. | Step 3 |
| `timeout` | The device neither started playing nor reported an error within the window. `responded` tells you whether it answered the request at all. | Step 4 |
| `template_error` | The message template did not render, so nothing was ever requested. The `error` attribute has the rendering error. | Step 5 |
| `unknown` | No delivery and no probe has completed yet since startup, or a request was replaced by a newer one before any evidence arrived. Wait one probe interval (5 minutes by default) or trigger an announcement. | Step 1 again |

`last_tts_success` (`sensor.<device>_last_tts_success`) is the last moment
a delivery to this device was confirmed. If it is more than a day old on a
speaker you announce to daily, the speaker has been silently failing since
then.

## Step 2: `fetch_failed`, the device cannot reach Home Assistant

The `url_source` attribute says which Home Assistant URL the device was
given: `internal_url`, `external_url`, `override` (a per-device URL set in
the options, shown in the `url_override` attribute), or nothing (a URL
outside Home Assistant, for example a radio stream).

1. Look for the repair issue **"<device> cannot fetch announcements from
   Home Assistant"** under Settings, Repairs. It appears after two
   consecutive fetch failures and names the URL that failed.
2. Check `subnet_mismatch` on the outcome sensor. `true` means the
   speaker's IP is not on the subnet Home Assistant's `internal_url`
   address sits on. Traffic then crosses a router or firewall, and a rule
   that blocks the speaker's VLAN from reaching Home Assistant's port
   produces exactly this outcome (the 2026-09-21 incident). `null` means
   the placement could not be determined because `internal_url` is a
   hostname; pin it to an address (Settings, System, Network) so this check
   works.
3. From a phone or laptop on the speaker's network, open the URL from
   `content_id` in a browser. If it does not load, the network is blocking
   it. If it loads, the speaker cannot resolve the hostname in the URL: use
   an IP address in `internal_url`.
4. If `url_source` is `external_url`, the speaker was given the public
   address. Speakers on the LAN should receive `internal_url`; check that
   `internal_url` is set and that the automation did not request the
   external URL.
5. If only some speakers can reach the `internal_url` address (a
   multi-VLAN host where the automatic URL picked an interface the other
   VLAN cannot route to), give those speakers their own base URL: Settings,
   Devices and services, Google Cast, Configure, tick "Edit per-device URL
   overrides next" under Delivery health, pick the device, enter
   `http://<address>:8123`. Every Home Assistant URL sent to that device,
   from `tts.speak`, `cast.announce`, `play_media`, and the probe, is
   re-based onto it; `url_source` then reads `override`. An empty URL
   removes the override. Overrides are per device, so a speaker group needs
   its own entry, and a leader that moves to another subnet still fetches
   from the group's override.

The issue clears itself as soon as a delivery to that device succeeds.

## Step 3: `unreachable`, no Cast channel

1. Is the media player entity available? If not, discovery still sees the
   device (or the entity would not exist) but the socket to port 8009 could
   not be opened. Every probe cycle records `unreachable` for it and, after
   two in a row, the repair issue **"<device> has no Cast connection"**
   appears. Power-cycle the speaker; if it fails again, check that TCP 8009
   from Home Assistant to the device is allowed.
2. If the entity is available and the outcome still reads `unreachable`,
   the channel dropped between the last status and the request. The next
   probe (within the interval) re-evaluates; if it stays `unreachable`, the
   device accepts mDNS and 8008 but not 8009. A firewall rule that permits
   discovery but not the Cast channel does this.

## Step 4: `timeout`, no verdict inside the window

Check `responded`:

- `false`: the device did not answer the play request at all. This matches
  pychromecast issue 1247, a hung app launch while the device keeps
  heartbeating. Power-cycle the device. After two consecutive probe
  timeouts the probe stops trying (`circuit_open: true`) and retries with
  growing delays; a successful probe or announcement closes the circuit.
- `true`: the device answered the request but never reported BUFFERING,
  PLAYING, or an error for that content. For a speaker group, see Step 6.
  For a single speaker this is rare; if it repeats, download diagnostics
  (Step 7) and look at the ledger for the device.

## Step 5: `template_error`, the message never rendered

The `error` attribute carries the rendering error, for example
`int got invalid input 'unknown'`, and a repair issue **"An announcement
template failed to render"** shows the template text. The usual cause is a
sensor that is `unknown` or `unavailable` reaching a bare `| int` or
`| float`. Give the filter a default (`| int(0)`) or guard with
`is_number`. The issue clears the next time the same template renders.

This outcome is only produced for announcements sent through
`cast.announce`, which renders the template itself. In an automation, wrap
the template in `{% raw %} ... {% endraw %}` so it reaches the action
unrendered; otherwise the automation engine renders it first and a failure
stops the automation before any action runs (visible only in the automation
trace).

## Step 6: groups

Announcing to a speaker group goes through the group's leader. Open the
group's device page and look at **Leader** (`sensor.<group>_leader`):

- `leader_ip` is the member currently leading; `advertised_port` is the
  dynamic port the group announced. If the outcome sensor of the group
  reads `fetch_failed`, apply Step 2 to the leader's address.
- `members_span_subnets: true` means members sit on more than one subnet;
  a repair issue **"Speaker group <name> spans subnets"** names them. Group
  playback then depends on routing between those subnets, and the leader
  can move to another subnet on election, so the outcome can change from
  one announcement to the next. Placing all members on one subnet is the
  durable fix.
- Groups that buffer forever when probed (pychromecast issue 1197) can be
  excluded from probing with the "Probe speaker groups" option; device
  probing continues.

## Step 7: the diagnostics download

Settings, Devices and services, Google Cast, the three dots menu, Download
diagnostics. The file answers the question in one place:

- `urls`: the internal and external URL in use, whether each is pinned or
  automatic, and the adapter network the internal address sits on.
- `devices`: every discovered device with `last_outcome`, `last_success`,
  `last_seen`, `subnet`, `subnet_mismatch`, `consecutive_failures`, and the
  full last record.
- `groups`: leader and members with subnets.
- `ledger`: the last 50 delivery records in order, each with `source`,
  `outcome`, `content_id`, `url_source`, `responded`, `elapsed`, and the
  device's reported `player_state` and `idle_reason`.
- `registry_without_discovery`: devices Home Assistant remembers that
  discovery no longer reports. A duplicate or replaced speaker shows here;
  the **"<device> has not been seen for 7 days"** repair removes it after
  confirmation.
- `probe`: the probe options and the last decision per device (`probe`,
  `skipped_busy`, `skipped: circuit open for 480s more`, and so on).
- `repairs`: active issue ids.

## Step 8: alerting so this is not found by hand again

Every resolved record fires a `cast_delivery_result` event with the same
fields as the ledger. The blueprint in `blueprints/automation/trooperthorn/`
sends a notification whenever an outcome other than `ok` (and other than a
probe skipped for playback) is recorded, naming the device, the outcome,
and the error. Import it from the repository or copy the file into
`blueprints/automation/`.

## What the tool cannot tell you

- Whether the audio was audible: a device that plays at volume zero
  reports `ok`.
- Whether the TTS engine produced the right words: the engine's output is
  outside the delivery path.
- Whether a fault is specific to the TTS proxy handler rather than the
  network: the probe fetches a silent clip through the same server, host,
  port, and TLS settings, but not through the TTS cache. A broken TTS cache
  directory would show as `fetch_failed` on announcements while probes
  stay `ok`; that combination points at the TTS integration, not the
  network.

## The Delivery health checkboxes disagree with what is running

Trust `sensor.<device>_tts_outcome`, not the form. Its attributes name the
`source` (`probe` or `play_media`) and the `content_id`; a `content_id` under
`/api/cast/probe/` and a `checked_at` on a fixed cadence mean the prober is
running whatever the options screen shows.

Before this was fixed, the options flow built the Delivery health section's
suggested values only from keys already present in the config entry's options,
while `probe_options()` fell back to the defaults for anything missing. An
entry whose options had never been saved therefore drew every checkbox
unchecked while probing ran every 300 seconds. The symptom was a Google Home
or Nest Mini clicking on a five minute cadence with no automation to blame:
the payload is silent, but the device wakes and emits its own connect sound
each time a receiver launches.

Both readers now take their defaults from `HEALTH_DEFAULTS` in `const.py`, so
the form shows what is in effect. On an entry saved before the fix, pressing
Submit on that screen once writes the options and removes any ambiguity.
