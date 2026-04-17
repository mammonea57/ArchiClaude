from pathlib import Path

from tests.fixtures.loader import load_reference_parcels


def test_loader_returns_all_5_reference_parcels() -> None:
    parcels = load_reference_parcels()
    ids = [p.id for p in parcels]
    assert set(ids) == {
        "paris_8e_ug_reference",
        "nogent_sur_marne_ub_reference",
        "saint_denis_um_reference",
        "versailles_ua_reference",
        "meaux_uc_reference",
    }


def test_reference_parcel_has_required_fields() -> None:
    parcels = load_reference_parcels()
    for p in parcels:
        assert p.id
        assert p.insee and len(p.insee) == 5
        assert p.section
        assert p.numero
        assert p.zone_plu_code


def test_loader_raises_if_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.yaml"
    try:
        load_reference_parcels(path=missing)
        raise AssertionError("Should have raised")
    except FileNotFoundError:
        pass
