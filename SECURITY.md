# Security Policy

## Reporting a vulnerability

Do not open a public issue containing exploit details, tokens, private
addresses, or logs. Use GitHub's private vulnerability-reporting feature for
this repository. If private reporting is unavailable, open a minimal issue
asking the maintainer to establish a private channel; omit technical details.

Include the affected version or commit, prerequisites, impact, a minimal
reproduction, and suggested remediation. Remove access tokens, internal and
external URLs, device names, and network addresses.

## Response targets

These are project targets, not an SLA: acknowledge critical and high reports
in three business days, establish severity and containment in seven, and
publish a coordinated fix as soon as it is safely validated. Lower-severity
issues are prioritized by exploitability and impact.

## Supported version

Only the latest published release and the default branch receive security
fixes. Operators should update Home Assistant and this integration promptly
and retain a tested rollback or backup. Removing the custom component returns
the instance to the core cast integration.

## Security boundaries

The integration accepts unauthenticated data from devices on the local
network (mDNS records, HTTP setup endpoints, and the Cast channel on port
8009), serves media URLs to those devices, and writes to the Home Assistant
state machine, the issue registry, and the event bus. It inherits core cast's
Home Assistant Cast system user with administrator group membership, whose
refresh token is sent to a device when a dashboard view is cast. Trust
boundaries and the advisory findings are in `THREAT-MODEL.md`.
