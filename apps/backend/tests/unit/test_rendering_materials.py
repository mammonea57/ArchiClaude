from core.rendering.materials_catalog import Material, get_material, load_materials


def test_load_materials_returns_list():
    materials = load_materials()
    assert len(materials) >= 65
    assert all(isinstance(m, Material) for m in materials)


def test_materials_have_required_fields():
    materials = load_materials()
    for m in materials:
        assert m.id
        assert m.nom
        assert m.categorie
        assert m.prompt_en
        assert m.couleur_dominante.startswith("#")
        assert len(m.couleur_dominante) == 7  # #RRGGBB


def test_get_material_by_id():
    m = get_material("enduit_blanc_lisse")
    assert m is not None
    assert m.nom == "Enduit blanc lisse"
    assert m.categorie == "facades"


def test_get_material_unknown_returns_none():
    assert get_material("inexistant") is None


def test_all_categories_present():
    materials = load_materials()
    cats = {m.categorie for m in materials}
    expected = {"facades", "toitures", "menuiseries", "clotures", "sols_exterieurs", "vegetal"}
    assert expected.issubset(cats)
