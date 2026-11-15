# Pre-Publication Gate Report

**Date:** 2026-11-15
**Release directory:** `C:\Users\asus\OneDrive\Desktop\LUNARIS-Release`
**Source repository:** `C:\Users\asus\OneDrive\Desktop\Lunaris Ana Dosya`

## 1. SHA256SUMS portability

Status: PASS

- All six required runtime data files are listed.
- All listed paths exist relative to the release root.
- Paths use portable forward slashes.
- Checksum format is compatible with `sha256sum -c`.
- All six checksums match.

Command:

```text
python -c "verify data/SHA256SUMS"
```

Result: 6 of 6 files OK.

Publication blocker: No.

## 2. CI without bundled scientific data

Status: PASS WITH QUALIFICATIONS

- Workflow separated into `unit-tests` and `data-dependent-tests`.
- Unit job runs data-independent tests.
- Data-dependent job runs only when the DEM is present.
- No tests were weakened or deleted.

Command:

```text
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Result: YAML parsed successfully; jobs `unit-tests` and `data-dependent-tests`.

Publication blocker: No, but the data-dependent job requires the external DEM.

## 3. LUNARIS_DATA_DIR defaults

Status: PASS

- Default configuration resolves to the bundled release data.
- External `LUNARIS_DATA_DIR` controls both DEM and kernel discovery.
- Paths with spaces were not explicitly tested, but `Path` handling is used.
- Missing DEM and missing kernel diagnostics remain explicit.

Commands:

```text
LUNARIS_DATA_DIR=<release-root> python -c "import horizon_analysis, ephemeris_engine; print(...)"
```

Result: DEM and kernel paths resolved under the configured root.

Publication blocker: No.

## 4. Provenance and coverage-error semantics

Status: PASS WITH QUALIFICATIONS

- SPK and PCK coverage queries now distinguish `verified`, `query_failed`, and `no_coverage_reported`.
- Failed coverage queries no longer silently appear as valid empty coverage.
- Candidate-comparison provenance still lacks a dedicated test.
- `MOON_ME` availability is not verified at every requested epoch.
- Kernel coverage intervals are not automatically compared against every requested analysis interval.

Commands:

```text
python -m pytest tests/test_release_diagnostics.py -q -p no:cacheprovider
```

Result: 9 passed, 0 failed.

Publication blocker: No for release review, but provenance qualifications remain documented.

## 5. Regression tests

Status: PASS

Commands:

```text
python -m pytest tests/ -q -p no:cacheprovider
```

Result: 67 passed, 0 failed.

Publication blocker: No.

## 6. Source repository integrity

Status: PASS

- Original source repository was not modified during this gate audit.
- Modified source files remain the previously audited Phase 4 changes.

Publication blocker: No.

## Summary table

| Area | Status | Publication blocker? |
|---|---|---|
| SHA256SUMS portability | PASS | No |
| CI without bundled data | PASS WITH QUALIFICATIONS | No |
| LUNARIS_DATA_DIR defaults | PASS | No |
| Provenance and coverage errors | PASS WITH QUALIFICATIONS | No |
| Regression tests | PASS | No |
| Source repository integrity | PASS | No |

## Final status

READY WITH DOCUMENTED LIMITATIONS

The release candidate passes all locally available checks. Remaining limitations are documented and do not invalidate the release candidate for manual review.
PY