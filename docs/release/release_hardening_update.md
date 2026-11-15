## 15. Release hardening update

Completed:

- Python version consistency: Dockerfile updated to Python 3.11.
- Data distribution: `docs/data_distribution.md` and `data/SHA256SUMS` created.
- Configurable data directory: `LUNARIS_DATA_DIR` supported in release code.
- API production configuration: CORS controlled by `LUNARIS_CORS_ORIGINS`.
- Frontend API base: `LUNARIS_API_BASE` supported in `south_pole_3d.py`.
- Scientific runtime diagnostics: `tests/test_release_diagnostics.py` added.
- CI preparation: `.github/workflows/ci.yml` created.
- GitHub Pages compatibility documented in `docs/github_pages.md`.

Validation:

- `python -m pytest tests/ -q -p no:cacheprovider`: 66 passed.
- Backend and frontend smoke tests passed.

Remaining items:

- Docker image not built because Docker is unavailable.
- No published deployment URL or `LUNARIS_API_BASE` is documented.
- Provenance and kernel-coverage qualifications from Phase 4 remain.

Updated final status: CONDITIONALLY READY — SPECIFIC ITEMS REMAIN.
