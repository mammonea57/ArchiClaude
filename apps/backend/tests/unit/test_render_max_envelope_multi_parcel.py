"""Unit tests for the multi-parcel fusion helpers in render_max_envelope.

Covers ``_fuse_parcels``, ``_idu_to_ref``, ``_load_parcels_from_geojson`` and
``_zone_from_overlays_strict`` — the pure, network-free building blocks of the
multi-parcel mode introduced for the Nogent G0123+G0124+G0125 unité foncière.
The full end-to-end sanity check (network → IGN/Géorisques → envelope) is
covered by :func:`render_max_envelope._test_nogent_multi`.

Memory feedback_dont_truncate_prod_db : we run pytest on this single module
only, never ``pytest tests/`` which has a fixture that TRUNCATEs the dev DB.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parents[1]
_RENDER_SRC = _REPO / "apps" / "render-service"
for p in (_BACKEND, _RENDER_SRC):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Import the script as a module — it lives under apps/backend/scripts/.
import importlib.util
_SCRIPT_PATH = _BACKEND / "scripts" / "render_max_envelope.py"
_spec = importlib.util.spec_from_file_location("render_max_envelope", _SCRIPT_PATH)
rme = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rme)


# ---------------------------------------------------------------------------
# Fixture data — the actual Nogent 3-parcel bundle saved as a refs file.
# ---------------------------------------------------------------------------


NOGENT_3P_PATH = _REPO / "refs" / "cadastre" / "nogent_94052_G0123_G0124_G0125.json"


def _load_nogent_3p():
    assert NOGENT_3P_PATH.exists(), f"missing fixture {NOGENT_3P_PATH}"
    return rme._load_parcels_from_geojson(NOGENT_3P_PATH)


# ---------------------------------------------------------------------------
# _idu_to_ref
# ---------------------------------------------------------------------------


def test_idu_to_ref_nogent_canonical():
    code_insee, section, numero = rme._idu_to_ref("940520000G0123")
    assert code_insee == "94052"
    assert section == "0G"
    assert numero == "0123"


def test_idu_to_ref_short_numero_padding():
    # IDU with a 3-digit numero gets zero-padded
    _, _, numero = rme._idu_to_ref("940520000G0123")
    assert numero == "0123"


def test_idu_to_ref_rejects_truncated():
    with pytest.raises(ValueError):
        rme._idu_to_ref("94052")


def test_parse_idu_list_strips_spaces():
    out = rme._parse_idu_list("940520000G0123, 940520000G0124 ,940520000G0125")
    assert out == ["940520000G0123", "940520000G0124", "940520000G0125"]


# ---------------------------------------------------------------------------
# _load_parcels_from_geojson — local file, no network
# ---------------------------------------------------------------------------


def test_load_parcels_from_geojson_nogent_3p():
    parcels = _load_nogent_3p()
    assert len(parcels) == 3
    numeros = sorted(p.numero for p in parcels)
    assert numeros == ["0123", "0124", "0125"]
    surfaces = sorted(p.contenance_m2 for p in parcels)
    # Recorded surfaces in the fixture : 275, 473, 518 m².
    assert surfaces == [275, 473, 518]
    assert all(p.commune == "Nogent-sur-Marne" for p in parcels)
    assert all(p.code_insee == "94052" for p in parcels)


# ---------------------------------------------------------------------------
# _fuse_parcels — adjacency + unary_union + Lambert-93 area
# ---------------------------------------------------------------------------


def test_fuse_parcels_nogent_3p_area_band():
    parcels = _load_nogent_3p()
    fused_geojson, warnings, notes = rme._fuse_parcels(parcels)
    # No adjacency gap — the 3 Nogent parcels are contiguous.
    assert warnings == []
    # Fused area should be ~1266 m² (sum 1266; topology may shave <1 m²).
    individual_sum = sum(p.contenance_m2 for p in parcels)
    assert individual_sum == 1266
    # Notes record the fusion event.
    assert any("Fusion 3 parcelles" in n for n in notes)
    # GeoJSON is a (Multi)Polygon — area band 1260-1280 m² when re-projected.
    from shapely.geometry import shape
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer
    project = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform
    fused_m2 = shp_transform(project, shape(fused_geojson)).area
    assert 1240 < fused_m2 < 1290, fused_m2


def test_fuse_parcels_detects_non_adjacent():
    # Build a synthetic 2-parcel bundle where the 2nd is far away (in WGS84)
    # → expect a warning about non-adjacency.
    from core.sources.cadastre import ParcelleResult
    p1_geom = {
        "type": "Polygon",
        "coordinates": [[
            [2.0, 48.0], [2.0001, 48.0],
            [2.0001, 48.0001], [2.0, 48.0001], [2.0, 48.0],
        ]],
    }
    p2_geom = {
        "type": "Polygon",
        "coordinates": [[
            [5.0, 48.0], [5.0001, 48.0],
            [5.0001, 48.0001], [5.0, 48.0001], [5.0, 48.0],
        ]],
    }
    p1 = ParcelleResult(code_insee="00000", section="AA", numero="0001",
                        contenance_m2=100, commune="Test", geometry=p1_geom)
    p2 = ParcelleResult(code_insee="00000", section="AA", numero="0002",
                        contenance_m2=100, commune="Test", geometry=p2_geom)
    _, warnings, _ = rme._fuse_parcels([p1, p2])
    assert len(warnings) == 1
    assert "Non-adjacent" in warnings[0]
    assert "0002" in warnings[0]


def test_fuse_parcels_single_parcel_no_warning():
    parcels = _load_nogent_3p()[:1]
    _, warnings, _ = rme._fuse_parcels(parcels)
    # Single-parcel bundle skips the adjacency walk → no warning.
    assert warnings == []


# ---------------------------------------------------------------------------
# _zone_from_overlays_strict — mixed zoning warning
# ---------------------------------------------------------------------------


def test_zone_from_overlays_strict_mixed_zoning():
    """Two parcels in different PLU zones → warning + most-restrictive pick."""
    from shapely.geometry import Polygon
    from types import SimpleNamespace

    # Fake GpuWfsBundle with 2 zones.
    zones = [
        SimpleNamespace(
            libelle="UA1",
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0],
                ]],
            },
        ),
        SimpleNamespace(
            libelle="UA2",
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [1.0, 0.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0], [1.0, 0.0],
                ]],
            },
        ),
    ]
    bundle = SimpleNamespace(zones=zones)
    # Parcel A in UA1, Parcel B in UA2.
    parcel_a = Polygon([(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)])
    parcel_b = Polygon([(1.2, 0.2), (1.4, 0.2), (1.4, 0.4), (1.2, 0.4)])
    picked, warnings = rme._zone_from_overlays_strict(bundle, [parcel_a, parcel_b])
    assert picked == "UA1"  # alpha most restrictive
    assert len(warnings) == 1
    assert "Zonage PLUi mixte" in warnings[0]
    assert "UA1" in warnings[0] and "UA2" in warnings[0]


def test_zone_from_overlays_strict_uniform_no_warning():
    from shapely.geometry import Polygon
    from types import SimpleNamespace
    zones = [
        SimpleNamespace(
            libelle="UA1",
            geometry={
                "type": "Polygon",
                "coordinates": [[
                    [0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0],
                ]],
            },
        ),
    ]
    bundle = SimpleNamespace(zones=zones)
    parcel_a = Polygon([(0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.2)])
    parcel_b = Polygon([(1.1, 1.1), (1.2, 1.1), (1.2, 1.2), (1.1, 1.2)])
    picked, warnings = rme._zone_from_overlays_strict(bundle, [parcel_a, parcel_b])
    assert picked == "UA1"
    assert warnings == []
