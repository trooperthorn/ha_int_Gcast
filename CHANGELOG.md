# Changelog

Versions are calendar versions `YYYY.MM.DD.N`; tags carry no prefix. A merge
to `main` publishes the release; see `docs/operations.md`.

## Unreleased

### WP0, fork hygiene and provenance

- Forked `homeassistant/components/cast` verbatim from core tag `2026.9.2`
  (`33c3e0cca60e`); provenance and sync procedure in `UPSTREAM.md`.
- Ported core's 88 cast tests to `pytest-homeassistant-custom-component`
  and added a load test.
- Added the release and security baseline: ruff, strict mypy, pytest with
  coverage, hassfest and HACS validation, CodeQL and bandit, merge-to-main
  releases with SBOM, checksums, and attestations.

### Divergence from upstream

Inherited files edited by the fork, so an upstream reconciliation knows
where to look:

- `manifest.json`: `codeowners`, `documentation`, `issue_tracker`, `version`.
