export interface Project {
  id: string;
  name: string;
  status: "draft" | "analyzed" | "archived";
  created_at: string;
  confidence_score?: number;
}

export interface GeocodingResult {
  label: string;
  score: number;
  lat: number;
  lng: number;
  citycode: string;
  city: string;
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
