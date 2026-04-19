from schemas.pcmi6 import CameraConfig, RenderCreate, RenderOut
from schemas.rendering import MaterialOut, QuotaResponse


def test_camera_config_defaults():
    c = CameraConfig(lat=48.85, lng=2.35, heading=90)
    assert c.pitch == 0.0
    assert c.fov == 60.0


def test_render_create_minimal():
    r = RenderCreate(
        photo_source="mapillary",
        photo_source_id="abc123",
        photo_base_url="https://r2.example.com/photo.jpg",
        camera=CameraConfig(lat=48.85, lng=2.35, heading=90),
        materials_config={"facade": "enduit_blanc"},
    )
    assert r.materials_config["facade"] == "enduit_blanc"


def test_render_out_minimal():
    from datetime import datetime

    r = RenderOut(
        id="uuid",
        label=None,
        status="done",
        project_id="p1",
        photo_source="mapillary",
        photo_base_url="https://r2.example.com/p.jpg",
        render_url="https://r2.example.com/r.jpg",
        selected_for_pc=False,
        created_at=datetime.utcnow(),
        generation_duration_ms=42000,
    )
    assert r.status == "done"


def test_material_out():
    m = MaterialOut(
        id="enduit_blanc_lisse",
        nom="Enduit blanc lisse",
        categorie="facades",
        sous_categorie="enduits",
        texture_url="/materials/enduit_blanc_lisse.jpg",
        thumbnail_url="/materials/enduit_blanc_lisse_thumb.jpg",
        prompt_en="white smooth stucco walls",
        prompt_fr="enduit blanc lisse",
        couleur_dominante="#F5F5F5",
        conforme_abf=True,
    )
    assert m.regional is None


def test_quota_unlimited():
    q = QuotaResponse(credits_remaining=-1, provider="rerender")
    assert q.credits_remaining == -1
