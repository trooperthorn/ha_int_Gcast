# Google Cast for Home Assistant, delivery health fork

![GitHub Release](https://img.shields.io/github/v/release/trooperthorn/ha_int_Gcast?style=for-the-badge)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.9.0-blue.svg?style=for-the-badge)

An in-house fork of the Home Assistant `cast` integration that turns TTS and
Cast delivery failures into observable state: sensors, events, and repair
issues, instead of a log line nobody reads. It keeps the `cast` domain, so
installing it changes no entity ids, automations, or dashboards, and removing
it returns you to the core integration.

Why it exists, the decisions behind it, and the sync process against core are
in [DESIGN.md](DESIGN.md), [UPSTREAM.md](UPSTREAM.md), and
[RESEARCH.md](RESEARCH.md). Claims that were not looked up are in
[unverified.md](unverified.md).

*This is a community fork and is not affiliated with Google, Nabu Casa, or
the Open Home Foundation.*
