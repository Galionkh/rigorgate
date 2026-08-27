## Summary

Describe the problem and the smallest change that solves it.

## Evidence and data provenance

- What inputs or providers are affected?
- How are timestamps, missing values, and fallbacks handled?
- Could this introduce look-ahead or survivorship bias?

## Verification

- [ ] Compile check passes
- [ ] Unit tests pass
- [ ] Offline demo passes
- [ ] New behavior has tests
- [ ] Documentation is updated
- [ ] No secrets, personal data, or proprietary payloads are included

## Research-safety check

- [ ] The change does not present a score as a probability without calibration
- [ ] The change does not add unattended order execution
- [ ] Failure and incomplete evidence remain visible
