# GitHub Pages Compatibility

The generated viewer is a self-contained HTML file. It does not reference relative external assets.

For a future GitHub Pages deployment:

1. Build the viewer with a production API base URL:
   `python south_pole_3d.py --api-base https://<production-api> --no-show --output outputs/south_pole_3d.html`
   or set `LUNARIS_API_BASE=https://<production-api>`.

2. Ensure the selected API allows the GitHub Pages origin through `LUNARIS_CORS_ORIGINS`.

3. Publish only the generated static HTML from `outputs/` or a designated Pages directory.

4. Do not publish the backend, DEM, or SPICE kernels as static assets unless intentionally required.

5. The backend must remain separately deployed; GitHub Pages cannot run FastAPI.

No GitHub Pages deployment was performed.
