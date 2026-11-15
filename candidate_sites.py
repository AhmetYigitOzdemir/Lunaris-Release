"""Representative locations for the current Artemis III candidate regions."""

from __future__ import annotations

from typing import TypedDict


class CandidateSite(TypedDict):
    region: str
    site_id: str
    latitude_deg: float
    longitude_deg: float


# One published representative landing point for each of NASA's current nine
# regions. Longitudes are east-positive; negative values are wrapped by the
# coordinate and ephemeris functions when used.
CANDIDATE_SITES: tuple[CandidateSite, ...] = (
    {"region": "Peak near Cabeus B", "site_id": "PCB01", "latitude_deg": -83.7630, "longitude_deg": -69.9830},
    {"region": "Haworth", "site_id": "HW04", "latitude_deg": -86.5680, "longitude_deg": -21.4730},
    {"region": "Malapert Massif", "site_id": "MMA04", "latitude_deg": -86.3100, "longitude_deg": -0.4590},
    {"region": "Mons Mouton Plateau", "site_id": "MMP01", "latitude_deg": -85.1110, "longitude_deg": 26.7100},
    {"region": "Mons Mouton", "site_id": "MMO01", "latitude_deg": -85.4160, "longitude_deg": 31.8510},
    {"region": "Nobile Rim 1", "site_id": "NR101", "latitude_deg": -85.2950, "longitude_deg": 36.9170},
    {"region": "Nobile Rim 2", "site_id": "NR201", "latitude_deg": -84.0540, "longitude_deg": 56.4810},
    {"region": "de Gerlache Rim 2", "site_id": "dGR2_K2023", "latitude_deg": -88.4500, "longitude_deg": -67.8590},
    {"region": "Slater Plain", "site_id": "SP01", "latitude_deg": -87.4780, "longitude_deg": 124.5210},
)
