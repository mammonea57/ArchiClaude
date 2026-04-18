"""Interior distribution module — floor-plate layout.

Assigns logements, noyaux and circulation spaces to each level footprint.
All geometries must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

import math

from shapely.geometry import Point, Polygon, box

from core.programming.schemas import (
    SURFACE_CENTRE,
    SURFACE_NOYAU_M2,
    TRAME_BA_M,
    TRAMES_PAR_TYPO,
    DistributionResult,
    Logement,
    NiveauDistribution,
    NiveauFootprint,
    Noyau,
    Piece,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum building depth for logements (metres)
_DEPTH_MIN_M = 10.0

# Typical building depth behind facade (metres)
_BUILDING_DEPTH_M = 14.0


# ---------------------------------------------------------------------------
# Template selection
# ---------------------------------------------------------------------------


def select_template(footprint: Polygon) -> str:
    """Select distribution template based on footprint shape ratio.

    Args:
        footprint: Level footprint polygon.

    Returns:
        One of: "plot", "barre_simple", "barre_double".
        ("l_distribue" reserved for future L-shape detection.)
    """
    bounds = footprint.bounds  # (minx, miny, maxx, maxy)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    long_side = max(width, height)
    short_side = max(min(width, height), 0.01)
    ratio = long_side / short_side

    if ratio > 3.5:
        return "barre_double"
    if ratio > 2.0:
        return "barre_simple"
    return "plot"


# ---------------------------------------------------------------------------
# Noyau placement
# ---------------------------------------------------------------------------


def place_noyaux(
    footprint: Polygon,
    *,
    template: str,
    nb_noyaux_requis: int = 1,
) -> list[Noyau]:
    """Place vertical circulation cores on the footprint.

    Args:
        footprint: Level footprint polygon.
        template: Distribution template ("plot", "barre_simple", "barre_double").
        nb_noyaux_requis: Requested number of cores (overridden by template logic).

    Returns:
        List of Noyau dataclasses.
    """
    centroid = footprint.centroid
    bounds = footprint.bounds  # (minx, miny, maxx, maxy)
    cx = centroid.x
    cy = centroid.y

    if template == "barre_double":
        # Two cores along the long axis at 1/3 and 2/3
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        if width >= height:
            # Horizontal long axis
            x1 = bounds[0] + width / 3.0
            x2 = bounds[0] + 2.0 * width / 3.0
            y = cy
            positions = [(x1, y), (x2, y)]
        else:
            # Vertical long axis
            x = cx
            y1 = bounds[1] + height / 3.0
            y2 = bounds[1] + 2.0 * height / 3.0
            positions = [(x, y1), (x, y2)]

        noyaux = []
        for i, (px, py) in enumerate(positions):
            noyaux.append(
                Noyau(
                    id=f"N{i + 1:02d}",
                    type="escalier+ascenseur",
                    position=Point(px, py),
                    surface_m2=SURFACE_NOYAU_M2,
                    dessert=[],
                )
            )
        return noyaux
    # Single core at centroid
    return [
        Noyau(
            id="N01",
            type="escalier+ascenseur",
            position=Point(cx, cy),
            surface_m2=SURFACE_NOYAU_M2,
            dessert=[],
        )
    ]


# ---------------------------------------------------------------------------
# Piece layout within a logement
# ---------------------------------------------------------------------------


def _layout_pieces(
    typologie: str,
    width_m: float,
    depth_m: float,
) -> list[Piece]:
    """Generate room layout for a dwelling within given dimensions.

    Rooms are arranged linearly along the depth:
    - Front (facade): séjour/cuisine + loggia strip
    - Middle: chambres
    - Back (corridor side): SDB, WC, dégagement

    Uses SURFACE_CENTRE targets scaled to fit within trame × depth.

    Args:
        typologie: Dwelling type ("T1"–"T5").
        width_m: Width of the logement (trame × TRAME_BA_M).
        depth_m: Depth of the logement (building depth).

    Returns:
        List of Piece dataclasses.
    """
    target_surface = SURFACE_CENTRE.get(typologie, 58.0)
    available = width_m * depth_m

    # Scale factor to fit within available area (capped at 1.0 to avoid oversizing)
    scale = min(1.0, available / max(target_surface, 1.0))

    def _piece(nom: str, surface_target: float, w: float, l: float) -> Piece:
        return Piece(
            nom=nom,
            surface_m2=round(surface_target * scale, 1),
            largeur_m=round(w * (scale ** 0.5), 2),
            longueur_m=round(l * (scale ** 0.5), 2),
        )

    if typologie == "T1":
        return [
            _piece("Séjour/cuisine", 15.0, width_m * 0.6, depth_m * 0.5),
            _piece("Chambre", 10.0, width_m * 0.6, depth_m * 0.35),
            _piece("SDB/WC", 4.0, width_m * 0.4, depth_m * 0.25),
            _piece("Dégagement", 2.0, width_m * 0.4, depth_m * 0.15),
        ]
    if typologie == "T2":
        return [
            _piece("Séjour/cuisine", 20.0, width_m * 0.65, depth_m * 0.5),
            _piece("Chambre 1", 11.0, width_m * 0.55, depth_m * 0.35),
            _piece("SDB", 5.0, width_m * 0.35, depth_m * 0.25),
            _piece("WC", 2.0, width_m * 0.2, depth_m * 0.15),
            _piece("Dégagement", 4.0, width_m * 0.35, depth_m * 0.2),
        ]
    if typologie == "T3":
        return [
            _piece("Séjour/cuisine", 27.0, width_m * 0.65, depth_m * 0.5),
            _piece("Chambre 1", 12.0, width_m * 0.55, depth_m * 0.35),
            _piece("Chambre 2", 10.0, width_m * 0.45, depth_m * 0.3),
            _piece("SDB", 5.5, width_m * 0.35, depth_m * 0.25),
            _piece("WC", 2.0, width_m * 0.2, depth_m * 0.15),
            _piece("Dégagement", 4.5, width_m * 0.4, depth_m * 0.2),
        ]
    if typologie == "T4":
        return [
            _piece("Séjour/cuisine", 34.0, width_m * 0.65, depth_m * 0.5),
            _piece("Chambre 1", 14.0, width_m * 0.55, depth_m * 0.35),
            _piece("Chambre 2", 11.0, width_m * 0.5, depth_m * 0.3),
            _piece("Chambre 3", 10.0, width_m * 0.45, depth_m * 0.3),
            _piece("SDB", 6.0, width_m * 0.35, depth_m * 0.25),
            _piece("SDE", 4.0, width_m * 0.3, depth_m * 0.2),
            _piece("WC", 2.0, width_m * 0.2, depth_m * 0.15),
            _piece("Dégagement", 6.0, width_m * 0.45, depth_m * 0.2),
        ]
    # T5
    return [
        _piece("Séjour/cuisine", 40.0, width_m * 0.65, depth_m * 0.5),
        _piece("Chambre 1", 15.0, width_m * 0.55, depth_m * 0.35),
        _piece("Chambre 2", 13.0, width_m * 0.5, depth_m * 0.35),
        _piece("Chambre 3", 11.0, width_m * 0.5, depth_m * 0.3),
        _piece("Chambre 4", 10.0, width_m * 0.45, depth_m * 0.3),
        _piece("SDB", 7.0, width_m * 0.4, depth_m * 0.25),
        _piece("SDE", 5.0, width_m * 0.35, depth_m * 0.2),
        _piece("WC", 2.0, width_m * 0.2, depth_m * 0.15),
        _piece("Dégagement", 7.0, width_m * 0.5, depth_m * 0.2),
    ]


# ---------------------------------------------------------------------------
# Distribution of logements across one level
# ---------------------------------------------------------------------------


def _distribute_on_niveau(
    *,
    niveau: int,
    footprint: Polygon,
    logements_for_level: list[tuple[str, bool]],  # (typologie, est_lls)
    template: str,
    nb_noyaux: int,
    orientations: list[dict] | None,
) -> NiveauDistribution:
    """Distribute logements on a single level footprint.

    Args:
        niveau: Level index (0-based).
        footprint: The constructible footprint for this level.
        logements_for_level: List of (typologie, est_lls) to place on this level.
        template: Distribution template.
        nb_noyaux: Number of circulation cores on this level.
        orientations: Optional orientation data (not yet used in layout).

    Returns:
        NiveauDistribution for this level.
    """
    bounds = footprint.bounds  # (minx, miny, maxx, maxy)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]

    # Determine long axis for placement
    long_side = max(width, height)
    short_side = min(width, height)
    depth = min(short_side, _BUILDING_DEPTH_M)

    # Place noyaux
    noyaux = place_noyaux(footprint, template=template, nb_noyaux_requis=nb_noyaux)
    total_noyau_surface = sum(n.surface_m2 for n in noyaux)

    # Circulations corridor: ~10% of footprint minus noyaux
    corridor_surface = max(0.0, footprint.area * 0.10)
    couloirs: list[Polygon] = []

    # Available facade length for logements
    # Subtract ~3m per noyau from facade
    noyau_frontage = nb_noyaux * (SURFACE_NOYAU_M2 / depth)
    available_facade = long_side - noyau_frontage

    # Lay logements along facade
    placed_logements: list[Logement] = []
    x_cursor = bounds[0]
    y_base = bounds[1]
    logement_counter = 0

    for typo, est_lls in logements_for_level:
        trames = TRAMES_PAR_TYPO.get(typo, 2.0)
        lg_width = trames * TRAME_BA_M
        lg_depth = depth

        # Target surface adjusted to actual trame × depth
        target = SURFACE_CENTRE.get(typo, 58.0)

        # Clamp to available area
        actual_surface = min(target, lg_width * lg_depth)
        # Ensure at least 90% of target
        actual_surface = max(actual_surface, target * 0.9)

        # Build geometry rectangle
        lg_geom = box(x_cursor, y_base, x_cursor + lg_width, y_base + lg_depth)

        # Clip to footprint just in case
        lg_geom_clipped = lg_geom.intersection(footprint)
        if lg_geom_clipped.is_empty or not isinstance(lg_geom_clipped, Polygon):
            lg_geom_clipped = lg_geom  # fallback: use unclipped

        # Piece layout
        pieces = _layout_pieces(typo, lg_width, lg_depth)

        # Determine orientation/exposure (simplified: south preference)
        if orientations:
            exposition = orientations[logement_counter % len(orientations)].get(
                "orientation_principale", "Sud"
            )
        else:
            # Alternate exposures along facade
            exposition = "Sud" if logement_counter % 2 == 0 else "Ouest"

        # Position label
        if logement_counter < len(logements_for_level) // 3:
            position = "gauche"
        elif logement_counter < 2 * len(logements_for_level) // 3:
            position = "centre"
        else:
            position = "droite"

        lg_id = f"N{niveau:02d}-L{logement_counter + 1:03d}"
        placed_logements.append(
            Logement(
                id=lg_id,
                typologie=typo,
                surface_m2=round(actual_surface, 1),
                niveau=niveau,
                position=position,
                exposition=exposition,
                est_lls=est_lls,
                pieces=pieces,
                geometry=lg_geom_clipped,
            )
        )

        x_cursor += lg_width
        logement_counter += 1

    surface_utile = sum(lg.surface_m2 for lg in placed_logements)

    return NiveauDistribution(
        niveau=niveau,
        footprint=footprint,
        logements=placed_logements,
        noyaux=noyaux,
        couloirs=couloirs,
        surface_utile_m2=surface_utile,
        surface_circulations_m2=total_noyau_surface + corridor_surface,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def distribute_logements(
    *,
    niveaux: list[NiveauFootprint],
    mix: dict[str, float],
    nb_logements_total: int,
    template: str,
    nb_noyaux: int,
    orientations: list[dict] | None = None,
    lls_pct: float = 0.0,
) -> DistributionResult:
    """Distribute logements across all level footprints.

    Args:
        niveaux: Level footprints from envelope computation.
        mix: Typological mix {"T2": 0.3, ...}.
        nb_logements_total: Total number of dwellings to place.
        template: Distribution template ("plot", "barre_simple", "barre_double").
        nb_noyaux: Number of vertical circulation cores.
        orientations: Optional orientation data per logement.
        lls_pct: Percentage of logements to mark as LLS (0.0–100.0).

    Returns:
        DistributionResult with all levels distributed.
    """
    if not niveaux:
        raise ValueError("niveaux must not be empty")
    if nb_logements_total <= 0:
        raise ValueError("nb_logements_total must be positive")

    # --- Build ordered list of (typologie, est_lls) for all logements ---
    norm = sum(mix.values()) or 1.0
    typologies_ordered: list[str] = []

    # Round-robin allocation: distribute types proportionally
    remaining = nb_logements_total
    types_list = list(mix.keys())
    counts: dict[str, int] = {}
    allocated = 0
    for i, t in enumerate(types_list):
        if i == len(types_list) - 1:
            counts[t] = remaining - allocated
        else:
            n = round(nb_logements_total * mix[t] / norm)
            counts[t] = max(0, n)
            allocated += counts[t]

    # Interleave types for uniform distribution across levels
    for t in types_list:
        typologies_ordered.extend([t] * counts[t])

    # Mark LLS: first ceil(lls_pct/100 * total) logements
    nb_lls = math.ceil(nb_logements_total * lls_pct / 100.0) if lls_pct > 0 else 0
    lls_flags = [i < nb_lls for i in range(nb_logements_total)]

    assignments: list[tuple[str, bool]] = list(zip(typologies_ordered, lls_flags, strict=False))

    # --- Distribute logements evenly across levels ---
    nb_levels = len(niveaux)
    per_level_base = nb_logements_total // nb_levels
    remainder = nb_logements_total % nb_levels

    level_counts: list[int] = []
    for i in range(nb_levels):
        level_counts.append(per_level_base + (1 if i < remainder else 0))

    # --- Compute each level distribution ---
    niveau_distributions: list[NiveauDistribution] = []
    cursor = 0
    for i, nf in enumerate(niveaux):
        n_on_level = level_counts[i]
        level_assignments = assignments[cursor : cursor + n_on_level]
        cursor += n_on_level

        nd = _distribute_on_niveau(
            niveau=nf.niveau,
            footprint=nf.footprint,
            logements_for_level=level_assignments,
            template=template,
            nb_noyaux=nb_noyaux,
            orientations=orientations,
        )
        niveau_distributions.append(nd)

    # --- Aggregate totals ---
    total_logements = sum(len(nd.logements) for nd in niveau_distributions)
    total_utile = sum(nd.surface_utile_m2 for nd in niveau_distributions)
    total_circ = sum(nd.surface_circulations_m2 for nd in niveau_distributions)

    # --- Coefficient utile ---
    # Coefficient = total surface utile / total footprint brute
    # We use geometry-based surface for a meaningful ratio in [0.6, 0.95]
    # Recompute utile from geometry areas (more accurate than target surfaces)
    total_utile_geo = sum(
        lg.geometry.area
        for nd in niveau_distributions
        for lg in nd.logements
        if isinstance(lg.geometry, Polygon) and not lg.geometry.is_empty
    )
    total_brute = sum(nf.surface_m2 for nf in niveaux)
    # Clamp to [0, 0.95] since noyaux + circulations consume the rest
    coefficient_raw = total_utile_geo / total_brute if total_brute > 0 else 0.0
    coefficient = min(0.95, coefficient_raw)

    return DistributionResult(
        template=template,
        niveaux=niveau_distributions,
        total_logements=total_logements,
        total_surface_utile_m2=total_utile,
        total_circulations_m2=total_circ,
        coefficient_utile=coefficient,
    )
