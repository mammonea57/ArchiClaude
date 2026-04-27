export interface Project {
  id: string;
  name: string;
  status: "draft" | "analyzed" | "archived";
  created_at?: string;
  confidence_score?: number;
  brief?: Brief;
}

export interface GeocodingResult {
  label: string;
  score: number;
  lat: number;
  lng: number;
  citycode: string;
  city: string;
}

export interface FeasibilityResult {
  id: string;
  project_id: string;
  status: "pending" | "complete" | "error";
  // KPIs
  sdp_m2?: number;
  niveaux?: number;
  nb_logements?: number;
  stationnement?: number;
  emprise_pct?: number;
  pleine_terre_pct?: number;
  // PLU rules
  parsed_rules?: Record<string, string | null>;
  numeric_rules?: Record<string, unknown>;
  plu_validated?: boolean;
  plu_confidence?: number;
  // Typology
  mix_typologique?: Record<string, number>;
  // Compliance
  incendie?: string;
  pmr_ascenseur?: boolean;
  re2020_seuil?: string;
  lls_statut?: string;
  rsdu_obligations?: string[];
  // Servitudes / alerts
  alerts?: Array<{ level: "info" | "warning" | "critical"; type: string; message: string }>;
  // Architecture note
  architecture_note_md?: string;
  // Raw feasibility note
  feasibility_summary?: string;
}

export interface Brief {
  destination: string;
  cible_nb_logements?: number;
  mix_typologique: Record<string, number>;
  cible_sdp_m2?: number;
  hauteur_cible_niveaux?: number;
  emprise_cible_pct?: number;
  stationnement_cible_par_logement?: number;
  espaces_verts_pleine_terre_cible_pct?: number;
}

// SP2-v2a BuildingModel payload (subset of fields used by frontend)
export interface BuildingModelRoom {
  id: string;
  type: string;
  surface_m2: number;
  polygon_xy: Array<[number, number]>;
  label_fr: string;
}

export interface BuildingModelOpening {
  id: string;
  type: string;
  wall_id: string;
  position_along_wall_cm: number;
  width_cm: number;
  height_cm: number;
}

export interface BuildingModelWall {
  id: string;
  type: string;
  thickness_cm: number;
  geometry: { type: string; coords: Array<[number, number]> };
}

export interface BuildingModelCellule {
  id: string;
  type: "logement" | "commerce" | "tertiaire" | "parking" | "local_commun";
  typologie?: string;
  surface_m2: number;
  polygon_xy: Array<[number, number]>;
  orientation?: string[];
  template_id?: string;
  rooms: BuildingModelRoom[];
  walls: BuildingModelWall[];
  openings: BuildingModelOpening[];
  /** Explicit axis-aligned jardin polygon for RDC logements. When set,
   *  the frontend renders this polygon directly instead of extruding
   *  the jardin from the apt's exterior walls. */
  jardin_polygon_xy?: Array<[number, number]> | null;
}

export interface BuildingModelCirculation {
  id: string;
  polygon_xy: Array<[number, number]>;
  surface_m2: number;
  largeur_min_cm: number;
}

export interface BuildingModelNiveau {
  index: number;
  code: string;
  usage_principal: string;
  hauteur_sous_plafond_m: number;
  surface_plancher_m2: number;
  cellules: BuildingModelCellule[];
  circulations_communes?: BuildingModelCirculation[];
}

export interface BuildingModelConformiteAlert {
  level: "info" | "warning" | "error";
  category: string;
  message: string;
  affected_element_id?: string;
}

export interface BuildingModelConformiteCheck {
  pmr_ascenseur_ok: boolean;
  pmr_rotation_cercles_ok: boolean;
  incendie_distance_sorties_ok: boolean;
  plu_emprise_ok: boolean;
  plu_hauteur_ok: boolean;
  plu_retraits_ok: boolean;
  ventilation_ok: boolean;
  lumiere_ok: boolean;
  alerts: BuildingModelConformiteAlert[];
}

export interface BuildingModelPayload {
  metadata: { id: string; project_id: string; address: string; zone_plu: string; version: number };
  site: {
    parcelle_geojson?: unknown;
    parcelle_surface_m2: number;
    voirie_orientations: string[];
    north_angle_deg?: number;
  };
  envelope: {
    footprint_geojson?: unknown;
    emprise_m2: number;
    niveaux: number;
    hauteur_totale_m: number;
    hauteur_rdc_m: number;
    hauteur_etage_courant_m: number;
  };
  core: {
    position_xy: [number, number];
    surface_m2: number;
    ascenseur: unknown;
    /** Actual rectangular polygon of the core (4 corner tuples). Provided
     * when the core was placed by a topology-aware handler (e.g. L-layout
     * right-half-of-landlocked-slot rule). Absent for legacy heuristic
     * placements. */
    polygon_xy?: [number, number][] | null;
  };
  niveaux: BuildingModelNiveau[];
  conformite_check?: BuildingModelConformiteCheck;
}

// DB row wrapper returned by GET /projects/{id}/building_model
export interface BuildingModelRow {
  id: string;
  project_id: string;
  version: number;
  model_json: BuildingModelPayload;
  conformite_check?: BuildingModelConformiteCheck;
  generated_at: string;
  source: string;
  dirty: boolean;
}

// --- Bilan promoteur (GET /projects/{id}/feasibility/bilan) ---

export interface BilanPoste {
  libelle: string;
  base: number;
  taux_ou_unitaire: number | string;
  montant_ht: number;
  tva_pct: number;
  montant_tva: number;
  montant_ttc: number;
}

export interface BilanChapitre {
  nom: string;
  postes: BilanPoste[];
  total_ht: number;
  total_tva: number;
  total_ttc: number;
  pct_depenses_ht: number;
}

export interface BilanRecettes {
  libre_surface_m2: number;
  libre_prix_ht_m2: number;
  libre_ht: number;
  libre_ttc: number;
  social_surface_m2: number;
  social_prix_ht_m2: number;
  social_ht: number;
  social_ttc: number;
  commerce_surface_m2: number;
  commerce_prix_ht_m2: number;
  commerce_ht: number;
  commerce_ttc: number;
  total_ht: number;
  total_ttc: number;
  prix_m2_shab_moyen_ht: number;
}

export interface BilanProgramme {
  terrain_m2: number;
  ces: number;
  sdp_m2: number;
  rendement_plan_shab_sur_sdp: number;
  shab_libre_m2: number;
  shab_social_m2: number;
  shab_commerce_m2: number;
  nb_parkings_ss_sol: number;
  nb_parkings_exterieurs: number;
  duree_chantier_mois: number;
}

export interface BilanResult {
  programme: BilanProgramme;
  recettes: BilanRecettes;
  foncier: BilanChapitre;
  travaux: BilanChapitre;
  honoraires: BilanChapitre;
  assurances: BilanChapitre;
  commercialisation: BilanChapitre;
  gestion_financiere: BilanChapitre;
  imprevus: BilanChapitre;
  depenses_total_ht: number;
  depenses_total_ttc: number;
  tva_sur_ventes: number;
  tva_deductible: number;
  tva_residuelle: number;
  marge_ht: number;
  marge_ttc: number;
  marge_pct_ht: number;
  marge_pct_ttc: number;
  charge_fonciere_max_ht: number;
  warnings: string[];
  option_label: string;
}
