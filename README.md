# Google Cast for Home Assistant, delivery health fork

![GitHub Release](https://img.shields.io/github/v/release/trooperthorn/ha_int_Gcast?style=for-the-badge)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.9.0-blue.svg?style=for-the-badge)

An in-house fork of the Home Assistant `cast` integration that turns TTS and
Cast delivery failures into observable state: sensors, events, and repair
issues, instead of a log line nobody reads. It keeps the `cast` domain, so
installing it changes no entity ids, automations, or dashboards, and
removing it returns you to the core integration.

## Why

On 2026-09-21 two speakers failed every announcement for a day and nothing
alerted. Core cast logs a delivery failure and does nothing else with it: a
silent speaker and a working speaker look the same to Home Assistant. This
fork receives the same media status callback core does and writes the
verdict where automations and people can see it.

## What it adds

- **`sensor.<device>_tts_outcome`**: the last delivery verdict for every
  cast device, one of `ok`, `fetch_failed`, `unreachable`, `timeout`,
  `template_error`, `skipped_busy`, `unknown`, with the evidence as
  attributes (which URL was used, whether the device answered, how long it
  took, what it reported).
- **`sensor.<device>_last_tts_success`**: when a delivery was last confirmed,
  kept across restarts.
- **`sensor.<group>_leader`**: which member leads a speaker group, its
  advertised port, the members, and whether they span subnets.
- **Active probing**: every five minutes each idle speaker plays a quarter
  second of silence served by this instance, so a speaker that can no longer
  reach Home Assistant is reported before an announcement is missed. Never
  interrupts playback, never touches a Chromecast with a display unless
  asked, backs off from devices that stop answering.
- **Per-device URL override**: Home Assistant has one internal URL, but a
  speaker on another VLAN or behind a proxy can be given its own base URL in
  the options. Announcements from `tts.speak`, `cast.announce`, plain
  `play_media`, and the probe are all rewritten for that device; radio
  streams and other third-party URLs are never touched.
- **Event `cast_delivery_result`** for every verdict, and a blueprint that
  turns non-`ok` verdicts into notifications.
- **Action `cast.announce`**: renders the message template itself so a
  template failure becomes a `template_error` verdict and a repair issue
  instead of a silent automation stop.
- **Repair issues** that name the device and the next action, and clear
  themselves: cannot fetch from Home Assistant, internal URL automatic on a
  multi-adapter host, group spans subnets, device unseen for 7 days (with a
  one-click removal), template failed.
- **Diagnostics** that answer "is TTS working, and if not, why" without a
  log: URLs and their adapters, every device's verdict and placement,
  groups, the last 50 delivery records, registry devices discovery no longer
  reports.
- Strict typing, a 45 s watchdog around every call into the Cast library,
  and an unload path core cast lacks.

## Install

Add this repository to HACS as a custom Integration repository, download,
restart. The existing Google Cast entry keeps working. Details, options, and
the release verification steps are in [docs/operations.md](docs/operations.md).
When something is not heard, start at
[docs/troubleshooting.md](docs/troubleshooting.md).

## Where to read more

| Document | Owns |
| --- | --- |
| [DESIGN.md](DESIGN.md) | Entity model, vocabulary, evidence rules, probing policy, decisions |
| [RESEARCH.md](RESEARCH.md) | Every fact the design relies on, with its source |
| [UPSTREAM.md](UPSTREAM.md) | Fork point and the sync procedure against core |
| [THREAT-MODEL.md](THREAT-MODEL.md) | Trust boundaries and advisory findings |
| [unverified.md](unverified.md) | Claims not looked up, with a check for each |
| [CHANGELOG.md](CHANGELOG.md) | Changes and the list of edits to inherited files |
| [docs/README.md](docs/README.md) | Index of the documentation |

## Known limitations

- The fork tracks deliveries it sends through the default media receiver
  and named cast apps. Media handed to a cast platform (for example Plex)
  is not tracked.
- `template_error` is only produced by `cast.announce`; automations that
  call `tts.speak` render their templates before the action runs.
- Subnet placement needs `internal_url` pinned to an IPv4 address.
- pychromecast is thread-based; the fork bounds every call with a watchdog
  but cannot kill a wedged thread (see DESIGN.md section 7).
- The library pin stays at `PyChromecast==14.0.10`, exactly as core pins it,
  so two library versions never resolve in one instance.

*This is a community fork and is not affiliated with Google, Nabu Casa, or
the Open Home Foundation.*
