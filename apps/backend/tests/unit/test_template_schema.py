import pytest
from pydantic import ValidationError

from core.templates_library.schemas import (
    DimensionsGrille,
    ReglementaireOk,
    Template,
    TemplateSource,
)


def _mini_template() -> Template:
    return Template(
        id="T2_test_v1", source=TemplateSource.MANUAL,
        typologie="T2", surface_shab_range=[45, 55],
        orientation_compatible=["nord-sud"],
        position_dans_etage=["milieu"],
        dimensions_grille=DimensionsGrille(
            largeur_min_m=6.0, largeur_max_m=7.5,
            profondeur_min_m=7.0, profondeur_max_m=8.5,
            adaptable_3x3=True,
        ),
        topologie={
            "rooms": [
                {"id": "r1", "type": "entree", "area_ratio": 0.08, "bounds_cells": [[0,0]]},
                {"id": "r2", "type": "sejour_cuisine", "area_ratio": 0.50, "bounds_cells": [[0,1],[1,0],[1,1]]},
                {"id": "r3", "type": "chambre_parents", "area_ratio": 0.32, "bounds_cells": [[0,2]]},
                {"id": "r4", "type": "sdb", "area_ratio": 0.10, "bounds_cells": [[1,2]]},
            ],
            "walls_abstract": [
                {"type": "porteur", "from_cell": [0,0], "to_cell": [0,3], "side": "north"},
            ],
            "openings_abstract": [
                {"type": "porte_entree", "wall_idx": 0, "position_ratio": 0.5, "swing": "interior_left"},
            ],
        },
        furniture_defaults={"sejour_cuisine": ["canape_3p", "table_6p"]},
        reglementaire_ok=ReglementaireOk(
            pmr_rotation_150=True, pmr_passages_80=True,
            ventilation_traversante=True, lumiere_naturelle_toutes_pieces_vie=True,
        ),
        tags=["compact", "moderne"],
    )


def test_template_validates():
    t = _mini_template()
    assert t.typologie == "T2"
    assert t.surface_shab_range == [45, 55]


def test_template_rejects_unknown_source():
    with pytest.raises(ValidationError):
        Template(
            id="X", source="random_source",  # invalid
            typologie="T2", surface_shab_range=[45, 55],
            orientation_compatible=["nord-sud"], position_dans_etage=["milieu"],
            dimensions_grille=DimensionsGrille(
                largeur_min_m=6.0, largeur_max_m=7.5,
                profondeur_min_m=7.0, profondeur_max_m=8.5,
                adaptable_3x3=True,
            ),
            topologie={"rooms": [], "walls_abstract": [], "openings_abstract": []},
            reglementaire_ok=ReglementaireOk(),
        )
