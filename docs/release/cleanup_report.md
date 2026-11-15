# Release Cleanup Report

**Date:** 2026-11-15
**Release directory:** `C:\Users\asus\OneDrive\Desktop\LUNARIS-Release`

## Cleanup performed

Deleted only Python cache artifacts:

- All `__pycache__` directories.
- All `.pyc` files.

No scientific data, source files, configuration, documentation, tests, generated outputs, or checksums were modified or deleted.

## Regression tests

Command:

```text
python -m pytest tests/ -q -p no:cacheprovider
```

Result: 67 passed, 0 failed.

## SHA-256 verification

Command:

```text
python -c "verify data/SHA256SUMS"
```

Result: 6 of 6 files OK.

- `data/ldem_80s_40m_float.img`: OK
- `data/ldem_80s_40m_float.lbl`: OK
- `data/Ephemeris/de440s.bsp`: OK
- `data/Ephemeris/moon_080317.tf`: OK
- `data/Ephemeris/moon_pa_de418_1950-2050.bpc`: OK
- `data/Ephemeris/pck00011.tpc`: OK

## Protected files

All required runtime data files remain present. No protected files were deleted or modified during cleanup.

## Final status

Release directory is clean of Python bytecode/cache artifacts and passes all available regression and checksum checks. No commits, pushes, deployments, or uploads were performed.
PY