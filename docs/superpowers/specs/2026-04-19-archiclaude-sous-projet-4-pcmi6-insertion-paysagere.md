# ArchiClaude — Sous-projet 4 : PCMI6 insertion paysagère & rendu IA

**Document de spécification — Design validé**
Date : 2026-04-19
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et objectif

### 1.1 Objectif

Générer la **pièce PCMI6** (document graphique d'insertion paysagère) du dossier de permis de construire via un pipeline qui combine :
- Éditeur 3D dans le navigateur pour placer le volume du projet sur une photo réelle du site
- Rendu IA photoréaliste via ReRender AI (pipeline multi-calques : photo + masque + normal map + depth map)
- Bibliothèque complète de matériaux (60+) avec UI non-invasive
- Historique complet des rendus avec traçabilité

### 1.2 Architecture d'abstraction — prête pour moteur interne

Tous les appels au provider de rendu passent par une interface abstraite `RenderProvider`. ReRender AI est l'implémentation v1. Le moteur SDXL + ControlNet interne (post-v1, quand GPUs disponibles) sera un autre `RenderProvider` — **aucune réécriture du code métier** nécessaire.

```python
class RenderProvider(Protocol):
    async def upload_image(self, image_bytes: bytes, name: str) -> str: ...
    async def render(self, *, base_image_id: str, mask_image_id: str, 
                      normal_image_id: str, depth_image_id: str,
                      prompt: str, negative_prompt: str, creativity: float, 
                      seed: int, style: str) -> str: ...  # returns job_id
    async def get_render_status(self, job_id: str) -> dict: ...
    async def get_account_status(self) -> dict: ...
```

### 1.3 Périmètre

Le SP4 s'appuie sur :
- **SP2** : footprint + hauteur du volume (calcul précis PLU)
- **SP1** : photos Mapillary / Street View du site
- **SP3** : cartouche PC normé pour le PCMI6 final

Il ajoute :
1. Abstraction `RenderProvider` + implémentation `ReRenderProvider`
2. Catalogue de matériaux (60+) avec images, prompts, métadonnées
3. Éditeur 3D React (React-Three-Fiber) pour calage du volume sur photo
4. Calibration caméra hybride (auto via métadonnées + affinage sliders)
5. Pipeline multi-calques (photo + masque + normal + depth)
6. Contrôle qualité IoU + re-render automatique si échec
7. Bouton "Régénérer avec variantes" (3 seeds différents)
8. Table `pcmi6_renders` avec historique complet (rétention 12 mois)
9. Rendering engine stockage R2 + worker ARQ

---

## 2. Architecture technique

### 2.1 Nouveau package backend `core/rendering/`

```
apps/backend/core/rendering/
├── __init__.py
├── provider.py               # RenderProvider Protocol interface
├── rerender_provider.py      # ReRender AI implementation
├── materials_catalog.py      # 60+ materials with metadata
├── quality_check.py          # IoU mask control
└── pcmi6_pipeline.py         # High-level orchestration
```

### 2.2 Nouveau package frontend `components/pcmi6/`

```
apps/frontend/src/components/pcmi6/
├── Pcmi6Editor.tsx           # Main editor page component
├── Scene3DEditor.tsx         # R3F canvas with volume + controls
├── CameraCalibrator.tsx      # Auto + fine-tuning sliders
├── MaterialsPicker.tsx       # Category tabs + visual grid
├── MaterialCard.tsx          # Single material card
├── RenderTrigger.tsx         # Generate button + progress
├── RendersGallery.tsx        # History of renders for this project
└── RenderDetail.tsx          # Selected render with download + compare
```

### 2.3 Nouvelle page frontend `/projects/[id]/pcmi6`

Accessible depuis la page PCMI du SP3 (bouton "Créer le PCMI6").

### 2.4 Endpoints API

```
POST   /projects/{id}/pcmi6/renders              → 202 {render_id, job_id}
GET    /projects/{id}/pcmi6/renders              → list of renders with metadata
GET    /projects/{id}/pcmi6/renders/{render_id}  → render detail
PATCH  /projects/{id}/pcmi6/renders/{render_id}  → update (select_for_pc, label)
DELETE /projects/{id}/pcmi6/renders/{render_id}  → delete render
POST   /projects/{id}/pcmi6/renders/{render_id}/regenerate_variants → 3 seeds variants
GET    /rendering/materials                       → materials catalog (cached)
GET    /rendering/quota                           → ReRender credits remaining
```

### 2.5 Nouvelles dépendances

**Backend** :
- `aiofiles>=23.0` pour streaming upload vers ReRender
- `scikit-image>=0.21` pour calcul IoU quality check

**Frontend** :
- `three>=0.160`
- `@react-three/fiber>=8.15`
- `@react-three/drei>=9.90` (TransformControls, OrbitControls, helpers)

### 2.6 Worker ARQ

`workers/rendering.py` — job `generate_pcmi6_render`. Durée estimée : 15-45 secondes (upload 4 images + render + polling + download).

---

## 3. Abstraction RenderProvider

### 3.1 Interface

```python
# core/rendering/provider.py
from typing import Protocol, Literal

class RenderProvider(Protocol):
    async def upload_image(self, *, image_bytes: bytes, name: str, 
                            content_type: str = "image/png") -> str:
        """Upload an image to the provider, return its image_id."""
    
    async def start_render(self, *,
                            base_image_id: str,
                            mask_image_id: str | None = None,
                            normal_image_id: str | None = None,
                            depth_image_id: str | None = None,
                            prompt: str,
                            negative_prompt: str = "cartoon, sketch, blurry, low quality",
                            creativity: float = 0.3,
                            seed: int | None = None,
                            style: str = "photorealistic_architectural",
                            resolution: Literal["1024", "1536"] = "1024") -> str:
        """Start a render job, return render_job_id."""
    
    async def get_render_status(self, render_job_id: str) -> dict:
        """Returns {status: 'pending'|'done'|'failed', result_url?: str, error?: str}."""
    
    async def get_account_credits(self) -> int:
        """Return remaining credits (or -1 for unlimited)."""
```

### 3.2 Implémentation ReRender

```python
# core/rendering/rerender_provider.py
class ReRenderProvider:
    """Implementation of RenderProvider using ReRender AI Enterprise API."""
    
    BASE_URL = "https://api.rerenderai.com/api/enterprise"
    
    def __init__(self, api_key: str):
        self._api_key = api_key
    
    async def upload_image(self, ...):
        # POST /upload (multipart)
    
    async def start_render(self, ...):
        # POST /render with full params
    
    async def get_render_status(self, ...):
        # GET /render/{id}
    
    async def get_account_credits(self):
        # GET /status
```

Configuration via env var : `RERENDER_API_KEY`. Fallback graceful (retourne `None` sur toutes les méthodes) si clé absente — l'UI montre "Feature indisponible — configurer ReRender AI".

### 3.3 Future provider interne (hors scope SP4)

Sera `InternalSDXLProvider` avec pipeline local :
- `upload_image` → sauvegarde sur R2/disque local
- `start_render` → enqueue sur GPU queue, appelle Stable Diffusion XL + ControlNet
- `get_render_status` → poll le GPU worker
- Même interface, zéro changement dans le code métier

---

## 4. Catalogue de matériaux (60+)

### 4.1 Structure des données

```python
# core/rendering/materials_catalog.py
@dataclass(frozen=True)
class Material:
    id: str                    # "enduit_blanc_lisse"
    nom: str                   # "Enduit blanc lisse"
    categorie: str             # "facades"
    sous_categorie: str        # "enduits"
    texture_url: str           # 512×512 texture preview
    thumbnail_url: str         # 120×120 thumbnail
    prompt_en: str             # "white smooth stucco walls"
    prompt_fr: str             # for UI tooltips
    couleur_dominante: str     # "#F5F5F5"
    conforme_abf: bool         # True if authorized by ABF
    regional: str | None = None  # "IDF", "Paris", None = universel
```

### 4.2 Catégories et contenu

**Façades (30+)** :
- Enduits (8) : blanc lisse, blanc gratté, crème, beige, gris clair, gris anthracite, ocre, terracotta
- Bardages bois (10) : douglas naturel, douglas grisé, mélèze, cèdre rouge, chêne brossé, red cedar, thermo-frêne, bois peint blanc, bois peint noir, clin vertical
- Pierres (8) : meulière, calcaire St-Leu, pierre de Paris, granit gris, basalte, pierre reconstituée claire, pierre sèche, schiste
- Briques (6) : rouge classique, rouge flammée, émaillée blanche, noire, rosée, silico-calcaire
- Bardages métal (8) : zinc patiné, zinc laqué gris, acier corten, aluminium anodisé, métal perforé, cassettes émaillées, tôle ondulée, bac acier

**Toitures (7)** : tuile plate IDF rouge, tuile plate vieillie, tuile canal, tuile mécanique, ardoise, zinc à joint debout, végétal extensif

**Menuiseries (6)** : bois naturel, bois peint blanc, aluminium blanc, aluminium anthracite, aluminium bronze, PVC blanc

**Clôtures (6)** : mur enduit + portail aluminium, grille fer forgé, clôture bois occultant, grillage + haie, mur en pierre sèche, palissade bois

**Sols extérieurs (6)** : pavés granit, dalles pierre reconstituée, béton désactivé, graviers blancs, graviers décoratifs, pavés autobloquants

**Végétal (5)** : arbres feuillus (chêne, érable), arbres persistants (pin), haies taillées (charme, if), arbustes (lavande, buis), pelouse

**Total : 65 matériaux**

### 4.3 UI frontend

**Composant `MaterialsPicker`** :
- Tabs par catégorie principale (Façades / Toitures / Menuiseries / Clôtures / Sols / Végétal)
- Grille visuelle 4 colonnes de cartes 120×120 avec nom en dessous
- Filtre recherche texte (instantané, client-side)
- Toggle "Conforme ABF uniquement"
- Palette de 8 couleurs cliquables pour filtrer par teinte
- Historique des 5 matériaux les plus utilisés par le promoteur en haut (favoris implicites calculés côté backend)

### 4.4 Stockage

Les matériaux sont des **données statiques** servies depuis `core/rendering/materials_data.json` — pas besoin de DB. Images de texture stockées dans `apps/frontend/public/materials/` (commit avec le code).

Endpoint `GET /rendering/materials` retourne le catalogue complet (cache-control 24h).

---

## 5. Éditeur 3D React (React-Three-Fiber)

### 5.1 Layout

Page `/projects/[id]/pcmi6` avec split vertical :
- **Gauche (65%)** : canvas R3F plein écran avec photo en fond + volume 3D
- **Droite (35%)** : panneau de contrôles (tabs)

Panneau droit — 4 onglets :
1. **Caméra** — auto-calibration + sliders affinage
2. **Matériaux** — MaterialsPicker avec sélection par surface (façade, toiture, etc.)
3. **Ouvertures** — ajout/suppression de fenêtres/portes (optionnel v1)
4. **Rendu** — bouton "Générer" + paramètres prompt

### 5.2 Scène 3D

**Caméra** : `PerspectiveCamera` positionnée et orientée selon calibration.

**Fond** : photo réelle affichée via `Plane` avec texture au plan z=-∞ (background) ou comme background CSS du canvas.

**Volume projet** : `mesh` avec géométrie extrudée depuis le footprint SP2 (shape 2D + extrusion verticale de hauteur).
- Matériau façade : `MeshStandardMaterial` avec texture choisie (preview) ou couleur unie
- Matériau toiture : idem pour la face supérieure

**Contrôles** :
- `<TransformControls>` pour translation (X/Y/Z du volume)
- Mode "rotate" via toggle pour rotation sur l'axe Z
- Mode "scale" désactivé (le volume est fixé par SP2, on n'autorise que repositionner)

**Éclairage** : `ambientLight` + `directionalLight` pour preview. L'éclairage final est celui de la photo (ReRender l'appliquera).

### 5.3 Export des 4 calques

Au clic sur "Générer le rendu" :

```tsx
async function exportLayers(gl: THREE.WebGLRenderer, scene: Scene, camera: Camera) {
  // 1. Photo de fond (déjà en R2 via Mapillary/SV)
  const basePhotoUrl = photoSourceUrl;
  
  // 2. Masque binaire
  const maskScene = cloneSceneWithMaterial(scene, new THREE.MeshBasicMaterial({ color: 0xffffff }));
  maskScene.background = new THREE.Color(0x000000);
  const maskPng = renderToPNG(gl, maskScene, camera);
  
  // 3. Normal map
  const normalScene = cloneSceneWithMaterial(scene, new THREE.MeshNormalMaterial());
  normalScene.background = new THREE.Color(0x7f7fff);  // neutral normal
  const normalPng = renderToPNG(gl, normalScene, camera);
  
  // 4. Depth map
  const depthScene = cloneSceneWithMaterial(scene, new THREE.MeshDepthMaterial());
  depthScene.background = new THREE.Color(0xffffff);
  const depthPng = renderToPNG(gl, depthScene, camera);
  
  return { basePhotoUrl, maskPng, normalPng, depthPng };
}
```

Les 4 calques sont envoyés au backend via un POST multipart.

---

## 6. Calibration caméra hybride

### 6.1 Étape 1 — Auto-calibration

Lors du chargement de la photo Mapillary / Street View, on extrait :
- `lat, lng` — position GPS du photographe
- `compass_angle` — azimut de visée (0=nord, 90=est)
- `focal_length` ou `fov` — focale (Mapillary: `camera_parameters`, SV: fov paramètre)

On calcule :
- **Position caméra** : (lat, lng) → Lambert-93 → origine scène 3D en (0,0,2.5m) (hauteur standard capture)
- **Direction** : compass_angle → rotation Y de la caméra 3D
- **Field of view** : 60-75° selon métadonnées (fallback 60° par défaut)

### 6.2 Étape 2 — Affinage manuel

Panneau "Caméra" avec 4 sliders :
- **Hauteur** (1.5m à 10m, défaut 2.5m)
- **Inclinaison** (-20° à +20° pitch, défaut 0°)
- **Focale** (35mm à 85mm équivalent, défaut 50mm)
- **Rotation horizontale** (-30° à +30° par rapport à l'azimut auto, pour corriger)

Le promoteur voit la scène s'ajuster en temps réel. Bouton "Réinitialiser calibration auto" pour revenir aux valeurs par défaut.

### 6.3 Validation

Petite croix rouge affichée sur la photo pour marquer le **centre exact de la parcelle** (projection depuis les coordonnées lat/lng de la parcelle). Si la croix est bien au milieu de la parcelle sur la photo, la calibration est bonne.

---

## 7. Pipeline multi-calques ReRender

### 7.1 Backend pipeline

```python
# core/rendering/pcmi6_pipeline.py
async def generate_pcmi6_render(
    *,
    project_id: str,
    photo_url: str,              # URL R2 de la photo d'entrée
    mask_bytes: bytes,           # PNG du masque
    normal_bytes: bytes,         # PNG normal map
    depth_bytes: bytes,          # PNG depth map
    materials_config: dict,      # {facade: "enduit_blanc", toiture: "zinc"...}
    camera_config: dict,         # {lat, lng, heading, pitch, fov}
    seed: int | None = None,
    provider: RenderProvider,
) -> dict:
    """Full pipeline returning render_url + metadata."""
    
    # 1. Build prompt from materials
    prompt = build_prompt(materials_config, camera_config)
    
    # 2. Upload photo + mask + normal + depth to provider
    photo_id = await provider.upload_image(image_bytes=photo_bytes, name="base.png")
    mask_id = await provider.upload_image(image_bytes=mask_bytes, name="mask.png")
    normal_id = await provider.upload_image(image_bytes=normal_bytes, name="normal.png")
    depth_id = await provider.upload_image(image_bytes=depth_bytes, name="depth.png")
    
    # 3. Start render
    render_job_id = await provider.start_render(
        base_image_id=photo_id,
        mask_image_id=mask_id,
        normal_image_id=normal_id,
        depth_image_id=depth_id,
        prompt=prompt,
        creativity=0.3,
        seed=seed or random.randint(1, 999999),
        style="photorealistic_architectural",
    )
    
    # 4. Poll status every 2s, max 60s
    for _ in range(30):
        status = await provider.get_render_status(render_job_id)
        if status["status"] == "done":
            break
        if status["status"] == "failed":
            raise RuntimeError(status.get("error", "render failed"))
        await asyncio.sleep(2)
    
    # 5. Download result
    result_url = status["result_url"]
    result_bytes = await download_bytes(result_url)
    
    # 6. Quality check IoU
    iou = compute_mask_iou(result_bytes, mask_bytes, threshold=0.5)
    
    # 7. If IoU < 0.8, retry with different seed (max 3 attempts)
    # ...
    
    # 8. Upload result to R2 + save metadata to DB
    # ...
    
    return {
        "render_url": r2_url,
        "iou_score": iou,
        "seed": seed,
        "prompt": prompt,
        "duration_ms": elapsed_ms,
    }
```

### 7.2 Construction du prompt

```python
def build_prompt(materials_config: dict, camera_config: dict) -> str:
    """Build ReRender prompt from materials + context."""
    parts = ["modern residential building"]
    
    # Materials
    for surface, material_id in materials_config.items():
        mat = MATERIALS[material_id]
        parts.append(f"{surface}: {mat.prompt_en}")
    
    # Lighting (from time of day — for v1, default daytime)
    parts.append("natural daylight, soft shadows")
    
    # Environment
    parts.append("realistic urban context, detailed, high quality, architectural photography")
    
    return ", ".join(parts)
```

### 7.3 Contrôle qualité IoU

```python
def compute_mask_iou(rendered_bytes: bytes, mask_bytes: bytes, threshold: float = 0.5) -> float:
    """Compute Intersection over Union between the rendered building area and the mask."""
    from skimage import io, color
    import numpy as np
    
    rendered = io.imread(BytesIO(rendered_bytes))
    mask = io.imread(BytesIO(mask_bytes), as_gray=True)
    
    # Detect "building" pixels in rendered image (where the volume should be)
    # Simplified: use the mask area as reference, check if rendered image differs from photo in that area
    rendered_binary = detect_building_region(rendered, mask_binary=(mask > 127))
    mask_binary = mask > 127
    
    intersection = np.logical_and(rendered_binary, mask_binary).sum()
    union = np.logical_or(rendered_binary, mask_binary).sum()
    
    return intersection / max(union, 1)
```

Si `iou < 0.8` → retry automatique avec seed différent (max 3 tentatives). Après 3 échecs, on retourne le meilleur rendu obtenu avec un warning "Qualité sous optimum — vérifier manuellement".

### 7.4 Régénération avec variantes

Endpoint dédié : `POST /projects/{id}/pcmi6/renders/{render_id}/regenerate_variants`.

Génère 3 rendus en parallèle avec 3 seeds différents (gardant tous les autres paramètres identiques). Le promoteur compare et sélectionne le meilleur.

Les 3 variantes sont stockées dans le champ `render_variants JSONB` du render parent.

---

## 8. DB — historique complet

### 8.1 Table `pcmi6_renders`

```sql
CREATE TABLE pcmi6_renders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    project_version_id UUID REFERENCES project_versions(id),
    
    -- Metadata
    label TEXT,
    
    -- Camera
    camera_lat NUMERIC,
    camera_lng NUMERIC,
    camera_heading NUMERIC,
    camera_pitch NUMERIC,
    camera_fov NUMERIC,
    
    -- Materials
    materials_config JSONB NOT NULL,
    
    -- Photo source
    photo_source TEXT,                 -- "mapillary" | "streetview"
    photo_source_id TEXT,
    photo_base_url TEXT,
    
    -- Input layers (R2 URLs)
    mask_url TEXT,
    normal_url TEXT,
    depth_url TEXT,
    
    -- Output
    render_url TEXT,
    render_variants JSONB,             -- [{seed, url}, ...]
    
    -- Provider metadata
    rerender_job_id TEXT,
    prompt TEXT,
    negative_prompt TEXT,
    creativity NUMERIC,
    seed INTEGER,
    
    -- Status
    status TEXT NOT NULL DEFAULT 'queued',  -- queued, generating, done, failed
    error_msg TEXT,
    
    -- Quality
    iou_quality_score NUMERIC,
    
    -- User action
    selected_for_pc BOOLEAN DEFAULT false,
    
    -- Meta
    created_at TIMESTAMPTZ DEFAULT now(),
    generation_duration_ms INTEGER,
    cost_cents NUMERIC(10, 4)
);

CREATE INDEX pcmi6_renders_project_created 
    ON pcmi6_renders(project_id, created_at DESC);

CREATE UNIQUE INDEX pcmi6_selected_per_version 
    ON pcmi6_renders(project_version_id) 
    WHERE selected_for_pc = true;
```

### 8.2 Politique de rétention 12 mois

Worker ARQ nocturne `workers/pcmi6_retention.py` qui :
1. Trouve les renders créés il y a > 365 jours ET `selected_for_pc = false`
2. Supprime les fichiers R2 (render_url, mask_url, normal_url, depth_url)
3. Met à jour le row DB : `render_url = NULL`, flag `purged = true`

Les renders `selected_for_pc = true` sont conservés indéfiniment (font partie du dossier PC officiel).

Cron ARQ : tous les jours à 03:00 UTC.

### 8.3 Coûts R2 estimés

- 4 fichiers × 5 MB = 20 MB par render
- ~50 renders par projet × 100 projets = 5000 renders/an = 100 GB/an
- Cloudflare R2 : $0.015/GB/mois = $1.5/mois pour 100 GB = **~$18/an** avant purge. Négligeable.

---

## 9. Frontend — éditeur complet

### 9.1 Page `/projects/[id]/pcmi6`

Structure :

```tsx
// app/projects/[id]/pcmi6/page.tsx
export default function Pcmi6Page() {
  return (
    <main className="h-screen flex flex-col">
      <Nav />
      <div className="flex-1 grid grid-cols-[1fr_400px]">
        <Scene3DEditor />
        <ControlsPanel>
          <Tabs>
            <Tab id="camera"><CameraCalibrator /></Tab>
            <Tab id="materials"><MaterialsPicker /></Tab>
            <Tab id="openings"><OpeningsEditor /></Tab>
            <Tab id="render"><RenderTrigger /></Tab>
          </Tabs>
        </ControlsPanel>
      </div>
    </main>
  );
}
```

### 9.2 Scene3DEditor

```tsx
<Canvas camera={{ position: cameraPos, fov: cameraFov }}>
  <Suspense fallback={null}>
    <BackgroundPhoto url={photoUrl} />
    <BuildingVolume 
      footprint={footprint} 
      hauteur_m={hauteur}
      materials={materialsConfig}
      position={volumePosition}
      rotation={volumeRotation}
    />
    <TransformControls
      object={buildingRef}
      mode={transformMode}  // "translate" | "rotate"
    />
    <OrbitControls enabled={orbitEnabled} />
    <ambientLight intensity={0.5} />
    <directionalLight position={[10, 10, 5]} intensity={0.8} />
  </Suspense>
</Canvas>
```

### 9.3 RenderTrigger

```tsx
function RenderTrigger() {
  const [status, setStatus] = useState<"idle" | "generating" | "done" | "failed">("idle");
  const [progress, setProgress] = useState(0);
  
  async function handleGenerate() {
    setStatus("generating");
    // 1. Export 4 layers from Three.js (mask, normal, depth PNGs)
    const layers = await exportLayers(gl, scene, camera);
    // 2. POST /projects/{id}/pcmi6/renders with multipart form
    const response = await fetch(`/api/v1/projects/${projectId}/pcmi6/renders`, { ... });
    // 3. Poll GET /renders/{id} every 2s
    // 4. Show result
  }
  
  return (
    <div>
      <Button onClick={handleGenerate} disabled={status === "generating"}>
        {status === "generating" ? `Génération... ${progress}%` : "Générer le rendu"}
      </Button>
      {status === "done" && <RenderResult url={renderUrl} />}
      {status === "done" && <Button onClick={regenerateVariants}>Régénérer avec variantes</Button>}
    </div>
  );
}
```

### 9.4 RendersGallery

Liste des renders existants pour ce projet, triée par date DESC :
- Vignette de chaque render
- Label éditable
- Badge "Sélectionné pour PC" sur celui qui va dans le dossier
- Boutons : Télécharger / Sélectionner pour PC / Supprimer
- Bouton "Comparer" pour afficher 2 renders côte-à-côte

### 9.5 Intégration avec SP3

Sur la page `/projects/[id]/pcmi` (du SP3), le bloc PCMI6 affiche :
- Si aucun render : "Aucun PCMI6 généré — créer maintenant" → lien vers `/projects/[id]/pcmi6`
- Si des renders existent : thumbnail du `selected_for_pc = true` + lien "Modifier"
- Au moment de la génération du dossier PC complet, le PCMI6 sélectionné est automatiquement inclus dans le PDF unique + ZIP

---

## 10. Critères de succès

| Critère | Seuil |
|---|---|
| Abstraction RenderProvider | Swap ReRender → moteur interne sans toucher le code métier |
| Catalogue matériaux | 65+ matériaux présents, images accessibles, prompts EN corrects |
| UI non-invasive | Aucun dropdown > 12 items |
| Auto-calibration caméra | 80% des photos Mapillary/SV donnent une calibration correcte sans affinage |
| Export 4 calques | Masque, normal, depth générés depuis R3F sans artefact |
| IoU quality check | ≥ 80% des rendus ont IoU ≥ 0.8 au premier essai |
| Retry automatique | Seeds alternatifs utilisés si IoU < 0.8, max 3 tentatives |
| Durée génération | P95 ≤ 45s (upload 4 images + render + download) |
| Historique | Tous les renders conservés (jusqu'à la purge 12 mois) |
| Rétention | Purge automatique après 365j, `selected_for_pc=true` protégés |
| Intégration PC | Le render `selected_for_pc=true` apparaît automatiquement dans le PDF unique + ZIP |

---

## 11. Hors scope SP4

- **Moteur interne SDXL + ControlNet** : post-v1, quand GPUs disponibles. L'abstraction `RenderProvider` le prépare.
- **Ombre portée dynamique** : on reste sur l'éclairage naturel par défaut. Un paramètre "heure de la journée" peut être ajouté en v1.1.
- **Rendu vidéo / flythrough** : non. PCMI6 = image statique.
- **Édition d'ouvertures en 3D** : v1 utilise les ouvertures calculées par SP2 (distribution). Édition visuelle reportée v1.2.
- **Rendu d'intérieur** : hors scope SP4. Le PCMI6 montre l'insertion extérieure uniquement.

---

## Fin du document
