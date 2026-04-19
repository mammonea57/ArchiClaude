"use client";

export type Coord = [number, number];

export interface BBox {
  minx: number;
  miny: number;
  maxx: number;
  maxy: number;
}

export function bboxOf(pts: Coord[]): BBox | null {
  if (pts.length === 0) return null;
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const [x, y] of pts) {
    if (x < minx) minx = x;
    if (y < miny) miny = y;
    if (x > maxx) maxx = x;
    if (y > maxy) maxy = y;
  }
  return { minx, miny, maxx, maxy };
}

export function polygonCentroid(pts: Coord[]): Coord {
  if (pts.length === 0) return [0, 0];
  let x = 0, y = 0;
  for (const [px, py] of pts) { x += px; y += py; }
  return [x / pts.length, y / pts.length];
}

/** Parse GeoJSON Polygon coordinates to a flat ring of Coord. */
export function coordsFromGeoJSON(geojson: unknown): Coord[] {
  if (!geojson || typeof geojson !== "object") return [];
  const coords = (geojson as { coordinates?: unknown }).coordinates;
  if (!Array.isArray(coords) || !Array.isArray(coords[0])) return [];
  const ring = coords[0] as unknown[];
  const out: Coord[] = [];
  for (const p of ring) {
    if (Array.isArray(p) && p.length >= 2 && typeof p[0] === "number" && typeof p[1] === "number") {
      out.push([p[0], p[1]]);
    }
  }
  return out;
}

/**
 * Build a world→svg projector given a bbox and target size.
 * SVG y axis grows down, so we flip Y.
 */
export function makeProjector(box: BBox, width: number, height: number, padding = 24) {
  const w = box.maxx - box.minx || 1;
  const h = box.maxy - box.miny || 1;
  const scale = Math.min((width - 2 * padding) / w, (height - 2 * padding) / h);
  // center the drawing
  const drawnW = w * scale;
  const drawnH = h * scale;
  const offsetX = (width - drawnW) / 2;
  const offsetY = (height - drawnH) / 2;
  return {
    scale,
    project: ([x, y]: Coord): Coord => [
      offsetX + (x - box.minx) * scale,
      height - offsetY - (y - box.miny) * scale,
    ],
  };
}

/** SVG path 'd' attribute from a ring of Coord, closed with Z. */
export function ringToPath(pts: Coord[], project: (c: Coord) => Coord): string {
  if (pts.length === 0) return "";
  const [x0, y0] = project(pts[0]);
  const rest = pts.slice(1).map((p) => {
    const [x, y] = project(p);
    return `L ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} ${rest} Z`;
}

/** Room-type color palette — chosen to read like an architect's plan. */
export function roomStyle(type: string): { fill: string; pattern?: string; stroke: string } {
  const WET = ["sdb", "salle_de_douche", "wc", "wc_sdb", "cuisine"];
  const LIVING = ["sejour", "sejour_cuisine", "entree"];
  const SLEEP = ["chambre_parents", "chambre_enfant", "chambre_supp"];
  const STORAGE = ["cellier", "placard_technique"];
  const OUTDOOR = ["loggia"];
  if (WET.includes(type)) return { fill: "#e0f2fe", pattern: "tile", stroke: "#0369a1" };
  if (LIVING.includes(type)) return { fill: "#fef3c7", pattern: "wood", stroke: "#92400e" };
  if (SLEEP.includes(type)) return { fill: "#ede9fe", pattern: "wood", stroke: "#5b21b6" };
  if (STORAGE.includes(type)) return { fill: "#f3f4f6", stroke: "#6b7280" };
  if (OUTDOOR.includes(type)) return { fill: "#dcfce7", pattern: "deck", stroke: "#166534" };
  return { fill: "#f8fafc", stroke: "#475569" };
}

const LABELS_FR: Record<string, string> = {
  entree: "Entrée",
  sejour: "Séjour",
  sejour_cuisine: "Séjour/Cuisine",
  cuisine: "Cuisine",
  sdb: "Salle de bain",
  salle_de_douche: "Salle d'eau",
  wc: "WC",
  wc_sdb: "SdB/WC",
  chambre_parents: "Chambre parents",
  chambre_enfant: "Chambre enfant",
  chambre_supp: "Chambre",
  cellier: "Cellier",
  placard_technique: "Placard tech.",
  loggia: "Loggia",
};

export function roomLabelFr(type: string, fallback?: string): string {
  return LABELS_FR[type] ?? fallback ?? type;
}

/** Short label for tight rooms. */
export function roomLabelShort(type: string): string {
  const SHORT: Record<string, string> = {
    sejour_cuisine: "Séj./Cuis.",
    chambre_parents: "Ch. parents",
    chambre_enfant: "Ch. enfant",
    chambre_supp: "Chambre",
    placard_technique: "Placard",
    salle_de_douche: "SdD",
  };
  return SHORT[type] ?? roomLabelFr(type);
}
