# Unverified claims

Every statement in this repository that was not read from a primary source
is listed here with the reason and the command a reader can run to check it.
Silence about uncertainty is the failure mode this file prevents.

| Claim | Where it is used | Why unverified | How to check |
| --- | --- | --- | --- |
| The Cast protocol's `idleReason` values are exactly `CANCELLED`, `INTERRUPTED`, `FINISHED`, `ERROR` | `health.py` outcome mapping | pychromecast 14.0.10 defines no enumeration; `MediaStatus.update` stores whatever string the device sends (`controllers/media.py`, line 324). The four values come from Google's Cast reference documentation, which is not a local source. | Read the `IdleReason` page of the Cast web receiver reference; grep the library for `idleReason` and confirm no enumeration exists. |
| A hung `launch_app()` (pychromecast #1247) reproduces on the Nest Audio on this network | `coordinator.py` watchdog and circuit breaker sizing | Reported upstream, not reproduced locally. The guards are designed so the fork does not depend on the answer. | Enable debug logging for `custom_components.cast` and look for `outcome=timeout responded=False` on that device. |
| The probe URL exercises the same server path as `/api/tts_proxy/` | `probe.py` | The probe serves a silent clip through a registered `HomeAssistantView` under the same `http` component, host, port, and TLS settings the TTS proxy uses. Whether a fault specific to the TTS proxy handler (cache directory, engine) would be missed is untested. | Break the TTS cache directory permissions and confirm the probe still reports `ok` while `tts.speak` fails; that gap is by design and documented in `docs/troubleshooting.md`. |
| The eighth cast device and the duplicate Nest Mini registry entry | Work order open questions 2 and 3 | Live instance state, not readable from this repository. | Download diagnostics after installing this fork; the `registry_without_discovery` list names registry devices with no discovery response. |
| Group leader IP equals the address the `_googlecast._tcp` group record advertises | `topology.py` | Verified by the work order author on 2026-09-22 for one group (`192.168.30.10:32046`); not verified for other firmware or for dynamic groups. | Compare `sensor.<group>_leader` against the Zeroconf browser in Home Assistant. |
