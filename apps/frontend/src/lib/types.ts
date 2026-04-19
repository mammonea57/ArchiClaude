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
