## Change

Describe the behavior and security impact. Name the work package (WP0 to WP5)
or the upstream reconciliation this change belongs to.

## Verification

- [ ] Python tests pass with coverage above the configured floor
- [ ] ruff and strict mypy pass
- [ ] Security workflow passes
- [ ] No secret, credential, token, private key, or production log was committed
- [ ] New network behavior is documented and failure-bounded (watchdog, backoff)
- [ ] `unverified.md` lists every claim that was not looked up
- [ ] `CHANGELOG.md` has an entry

## Risk and rollback

State affected trust boundaries and a rollback method. A HACS downgrade to the
previous release, or removing the custom component to return to core cast,
must both remain possible.
