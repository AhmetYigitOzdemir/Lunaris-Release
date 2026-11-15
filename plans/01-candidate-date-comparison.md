# Plan 1 — Candidate Region and Date Comparison

## Objective

Enable comparison of representative landing sites across the nine Artemis III candidate regions for a common mission epoch and surface duration, rather than limiting analysis to one map selection.

## Scope

1. Maintain a versioned candidate-site catalogue using representative coordinates published by NASA and the Lunar and Planetary Institute.
2. Provide API endpoints for the catalogue and for batch comparison.
3. Accept a mission start epoch and surface duration, then compute solar availability, the longest continuous sunlight interval, instantaneous terrain shadow, and Earth visibility.
4. Present results in a sortable HUD table and focus the map on a selected result.

## Acceptance Criteria

- The API returns the identity and source coordinate of all nine candidates.
- Changing the epoch or duration recalculates all rows with the same parameters.
- Incomplete DEM coverage is reported as `unknown`; sunlight is never assumed.
- Each candidate is exercised against the operational DEM through a dedicated pytest parameter.
- Output reports metrics independently and makes no claim that one site is a scientific winner.

Coordinate sources: [Wueller et al. (2026), Table A1](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2025JE009434), reconciled with NASA's current nine-region update: [NASA NTRS 20250011660](https://ntrs.nasa.gov/citations/20250011660).
