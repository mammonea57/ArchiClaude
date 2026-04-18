"""Unit tests for core.programming.plans.plan_niveau — plan de niveau generator.

TDD: tests written before implementation.
"""

from __future__ import annotations

from shapely.geometry import Point, Polygon

from core.programming.plans.plan_niveau import generate_plan_niveau
from core.programming.schemas import (
    Logement,
    NiveauDistribution,
    Noyau,
    Piece,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(w: float, h: float, ox: float = 0, oy: float = 0) -> Polygon:
    return Polygon([(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)])


def _piece(nom: str, surf: float = 15.0) -> Piece:
    return Piece(nom=nom, surface_m2=surf, largeur_m=3.0, longueur_m=surf / 3.0)


def _logement(
    id: str = "L01",
    typo: str = "T2",
    surf: float = 42.0,
    niveau: int = 0,
    pieces: list[Piece] | None = None,
) -> Logement:
    if pieces is None:
        pieces = [_piece("Séjour", 20.0), _piece("Chambre", 12.0), _piece("SDB", 5.0)]
    return Logement(
        id=id,
        typologie=typo,
        surface_m2=surf,
        niveau=niveau,
        position="centre",
        exposition="Sud",
        est_lls=False,
        pieces=pieces,
        geometry=_rect(6.0, 7.0),
    )


def _noyau() -> Noyau:
    return Noyau(
        id="N01",
        type="double",
        position=Point(20, 10),
        surface_m2=35.0,
        dessert=["L01", "L02"],
    )


def _niveau(niveau: int = 0, nb_logements: int = 2) -> NiveauDistribution:
    footprint = _rect(40.0, 20.0)
    logements = [
        _logement(f"L{i:02d}", niveau=niveau, typo="T2" if i % 2 == 0 else "T3")
        for i in range(nb_logements)
    ]
    couloir = _rect(40.0, 2.0, oy=9.0)
    return NiveauDistribution(
        niveau=niveau,
        footprint=footprint,
        logements=logements,
        noyaux=[_noyau()],
        couloirs=[couloir],
        surface_utile_m2=nb_logements * 42.0,
        surface_circulations_m2=80.0,
    )


# ---------------------------------------------------------------------------
# test_returns_svg
# ---------------------------------------------------------------------------


class TestReturnsSvg:
    def test_returns_svg_string(self) -> None:
        result = generate_plan_niveau(_niveau(), format="svg")
        assert isinstance(result, str)
        assert "<svg" in result

    def test_svg_closes_properly(self) -> None:
        result = generate_plan_niveau(_niveau(), format="svg")
        assert "</svg>" in result

    def test_returns_bytes_for_dxf(self) -> None:
        result = generate_plan_niveau(_niveau(), format="dxf")
        assert isinstance(result, bytes)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# test_contains_room_names
# ---------------------------------------------------------------------------


class TestContainsRoomNames:
    def test_sejour_in_output(self) -> None:
        n = _niveau()
        result = generate_plan_niveau(n, detail="pc_norme", format="svg")
        assert "Séjour" in result

    def test_chambre_in_output(self) -> None:
        n = _niveau()
        result = generate_plan_niveau(n, detail="pc_norme", format="svg")
        assert "Chambre" in result

    def test_all_logement_ids_or_typos_present(self) -> None:
        n = _niveau(nb_logements=3)
        result = generate_plan_niveau(n, detail="pc_norme", format="svg")
        # At least one logement identifier present
        assert "T2" in result or "T3" in result or "L00" in result


# ---------------------------------------------------------------------------
# test_schematic_vs_nf (pc_norme output is larger / more detailed)
# ---------------------------------------------------------------------------


class TestSchematicVsNf:
    def test_pc_norme_output_larger_than_schematique(self) -> None:
        n = _niveau()
        schematic = generate_plan_niveau(n, detail="schematique", format="svg")
        pc = generate_plan_niveau(n, detail="pc_norme", format="svg")
        assert isinstance(schematic, str)
        assert isinstance(pc, str)
        # pc_norme includes more detail (dimensions, surfaces etc.) → larger output
        assert len(pc) >= len(schematic)

    def test_schematique_is_valid_svg(self) -> None:
        n = _niveau()
        result = generate_plan_niveau(n, detail="schematique", format="svg")
        assert "<svg" in result

    def test_execution_detail_is_valid_svg(self) -> None:
        n = _niveau()
        result = generate_plan_niveau(n, detail="execution", format="svg")
        assert "<svg" in result

    def test_execution_larger_than_pc_norme(self) -> None:
        n = _niveau()
        pc = generate_plan_niveau(n, detail="pc_norme", format="svg")
        exe = generate_plan_niveau(n, detail="execution", format="svg")
        assert len(exe) >= len(pc)


# ---------------------------------------------------------------------------
# test_geometry_elements
# ---------------------------------------------------------------------------


class TestGeometryElements:
    def test_has_polygon_or_rect_for_walls(self) -> None:
        n = _niveau()
        result = generate_plan_niveau(n, detail="pc_norme", format="svg")
        assert "<polygon" in result or "<rect" in result or "<path" in result

    def test_niveau_zero_label_present(self) -> None:
        n = _niveau(niveau=0)
        result = generate_plan_niveau(n, detail="pc_norme", format="svg")
        # RDC or niveau 0 label
        assert "RDC" in result or "R+0" in result or "Niveau 0" in result or "0" in result
