"use client";

/**
 * Pattern library + compass + scale bar used across every plan.
 * Patterns are crafted to read like a proper 2D architect's plan:
 * oak parquet, ceramic tiles, terrace decking, ground hatch, concrete
 * section fill, vegetation, lawn, asphalt.
 */
export function PlanPatterns() {
  return (
    <defs>
      {/* Oak parquet — irregular planks */}
      <pattern id="pat-parquet" width="60" height="14" patternUnits="userSpaceOnUse">
        <rect width="60" height="14" fill="#f5e6c8" />
        <rect x="0" y="0" width="24" height="14" fill="#edd7ad" />
        <rect x="24" y="0" width="20" height="14" fill="#f0dcb7" />
        <rect x="44" y="0" width="16" height="14" fill="#e8d1a5" />
        <line x1="0" y1="14" x2="60" y2="14" stroke="#b88a4a" strokeWidth="0.3" />
        <line x1="24" y1="0" x2="24" y2="14" stroke="#b88a4a" strokeWidth="0.25" />
        <line x1="44" y1="0" x2="44" y2="14" stroke="#b88a4a" strokeWidth="0.25" />
      </pattern>

      {/* Bedroom parquet (warmer) */}
      <pattern id="pat-parquet-warm" width="60" height="14" patternUnits="userSpaceOnUse">
        <rect width="60" height="14" fill="#f3e4cc" />
        <rect x="0" y="0" width="28" height="14" fill="#eed5a9" />
        <rect x="28" y="0" width="18" height="14" fill="#f0dab0" />
        <rect x="46" y="0" width="14" height="14" fill="#e8caa0" />
        <line x1="0" y1="14" x2="60" y2="14" stroke="#a87a3a" strokeWidth="0.3" />
        <line x1="28" y1="0" x2="28" y2="14" stroke="#a87a3a" strokeWidth="0.25" />
        <line x1="46" y1="0" x2="46" y2="14" stroke="#a87a3a" strokeWidth="0.25" />
      </pattern>

      {/* Ceramic tiles — 20×20cm grid with grout (entrée, cuisine) */}
      <pattern id="pat-tiles" width="20" height="20" patternUnits="userSpaceOnUse">
        <rect width="20" height="20" fill="#cddbe8" />
        <line x1="20" y1="0" x2="20" y2="20" stroke="#7aa0bd" strokeWidth="0.5" />
        <line x1="0" y1="20" x2="20" y2="20" stroke="#7aa0bd" strokeWidth="0.5" />
      </pattern>

      {/* Small tile (bathroom) */}
      <pattern id="pat-tiles-small" width="10" height="10" patternUnits="userSpaceOnUse">
        <rect width="10" height="10" fill="#dbe9f4" />
        <line x1="10" y1="0" x2="10" y2="10" stroke="#a9c9e0" strokeWidth="0.35" />
        <line x1="0" y1="10" x2="10" y2="10" stroke="#a9c9e0" strokeWidth="0.35" />
      </pattern>

      {/* Terrace / deck — long wooden boards */}
      <pattern id="pat-deck" width="12" height="60" patternUnits="userSpaceOnUse">
        <rect width="12" height="60" fill="#d9bc8a" />
        <line x1="0" y1="0" x2="0" y2="60" stroke="#a37d49" strokeWidth="0.45" />
        <line x1="6" y1="0" x2="6" y2="60" stroke="#a37d49" strokeWidth="0.25" strokeDasharray="3 1 18 1 6" />
      </pattern>

      {/* Ground section hatch — 45° lines */}
      <pattern id="pat-ground" width="8" height="8" patternUnits="userSpaceOnUse">
        <path d="M 0 8 L 8 0" stroke="#6b7280" strokeWidth="0.55" />
      </pattern>

      {/* Concrete slab fill */}
      <pattern id="pat-concrete" width="14" height="14" patternUnits="userSpaceOnUse">
        <rect width="14" height="14" fill="#9ca3af" />
        <circle cx="3" cy="3" r="0.5" fill="#475569" />
        <circle cx="10" cy="7" r="0.4" fill="#475569" />
        <circle cx="5" cy="11" r="0.55" fill="#475569" />
      </pattern>

      {/* Béton armé — diagonales 45° fines (mur en coupe) */}
      <pattern id="pat-beton-arme" width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="6" height="6" fill="#d6d3d1" />
        <path d="M 0 6 L 6 0" stroke="#44403c" strokeWidth="0.45" />
        <path d="M -1.5 1.5 L 1.5 -1.5" stroke="#44403c" strokeWidth="0.45" />
        <path d="M 4.5 7.5 L 7.5 4.5" stroke="#44403c" strokeWidth="0.45" />
      </pattern>

      {/* Béton banché — hachures horizontales (dalle en coupe) */}
      <pattern id="pat-beton-banche" width="8" height="3" patternUnits="userSpaceOnUse">
        <rect width="8" height="3" fill="#cbd5e1" />
        <line x1="0" y1="1.5" x2="8" y2="1.5" stroke="#475569" strokeWidth="0.35" />
      </pattern>

      {/* Étanchéité — hachures horizontales serrées */}
      <pattern id="pat-etancheite" width="10" height="2" patternUnits="userSpaceOnUse">
        <rect width="10" height="2" fill="#1f2937" />
        <line x1="0" y1="1" x2="10" y2="1" stroke="#9ca3af" strokeWidth="0.35" />
      </pattern>

      {/* Isolation — petits points réguliers */}
      <pattern id="pat-isolation" width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="6" height="6" fill="#fef3c7" />
        <circle cx="2" cy="2" r="0.5" fill="#b45309" />
        <circle cx="5" cy="5" r="0.5" fill="#b45309" />
      </pattern>

      {/* Terre / fondations — stippling aléatoire (cailloux + remblais) */}
      <pattern id="pat-terre" width="22" height="22" patternUnits="userSpaceOnUse">
        <rect width="22" height="22" fill="#a8a29e" />
        <circle cx="3" cy="4" r="0.7" fill="#57534e" />
        <circle cx="14" cy="3" r="0.5" fill="#57534e" />
        <circle cx="9" cy="9" r="0.6" fill="#44403c" />
        <circle cx="18" cy="11" r="0.5" fill="#57534e" />
        <circle cx="5" cy="14" r="0.55" fill="#44403c" />
        <circle cx="13" cy="17" r="0.7" fill="#57534e" />
        <circle cx="20" cy="19" r="0.45" fill="#44403c" />
        <circle cx="2" cy="20" r="0.5" fill="#57534e" />
        <ellipse cx="11" cy="13" rx="1.2" ry="0.6" fill="#78716c" opacity="0.6" />
        <ellipse cx="6" cy="8" rx="0.9" ry="0.45" fill="#78716c" opacity="0.5" />
      </pattern>

      {/* Vegetation canopy (mass) */}
      <pattern id="pat-veg" width="28" height="28" patternUnits="userSpaceOnUse">
        <rect width="28" height="28" fill="#a7dab0" />
        <circle cx="7" cy="8" r="4" fill="#6bbe70" />
        <circle cx="20" cy="12" r="5" fill="#4ea055" />
        <circle cx="11" cy="21" r="4.5" fill="#58af5f" />
        <circle cx="22" cy="22" r="3.5" fill="#3d8f44" />
      </pattern>

      {/* Lawn — short grass */}
      <pattern id="pat-lawn" width="14" height="14" patternUnits="userSpaceOnUse">
        <rect width="14" height="14" fill="#c9e8ca" />
        <path d="M 2 14 L 2 10 M 5 14 L 5 8 M 9 14 L 9 11 M 12 14 L 12 9" stroke="#5aa15f" strokeWidth="0.4" />
        <path d="M 7 11 L 8 8 M 3 6 L 4 3 M 10 5 L 11 2" stroke="#5aa15f" strokeWidth="0.35" />
      </pattern>

      {/* Asphalt / road */}
      <pattern id="pat-road" width="18" height="18" patternUnits="userSpaceOnUse">
        <rect width="18" height="18" fill="#6b7280" />
        <circle cx="3" cy="3" r="0.4" fill="#3f4651" />
        <circle cx="10" cy="8" r="0.35" fill="#3f4651" />
        <circle cx="5" cy="13" r="0.5" fill="#3f4651" />
        <circle cx="14" cy="14" r="0.3" fill="#3f4651" />
      </pattern>

      {/* Drop shadow for buildings (mass plan) */}
      <filter id="fx-shadow" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur in="SourceAlpha" stdDeviation="1.4" />
        <feOffset dx="1.5" dy="2.5" result="offsetblur" />
        <feComponentTransfer>
          <feFuncA type="linear" slope="0.35" />
        </feComponentTransfer>
        <feMerge>
          <feMergeNode />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
  );
}

/** Full 8-pt compass rose — matches pro archi docs. */
export function NorthArrow({ x, y, size = 48, rotationDeg = 0 }: {
  x: number; y: number; size?: number; rotationDeg?: number;
}) {
  const r = size / 2;
  return (
    <g transform={`translate(${x}, ${y}) rotate(${rotationDeg})`}>
      <circle cx={0} cy={0} r={r + 2} fill="white" stroke="#cbd5e1" strokeWidth={0.6} />
      <circle cx={0} cy={0} r={r} fill="none" stroke="#94a3b8" strokeWidth={0.4} />
      <circle cx={0} cy={0} r={r * 0.55} fill="none" stroke="#cbd5e1" strokeWidth={0.35} />

      {/* Major points — N, E, S, O */}
      <polygon points={`0,${-r * 0.88} ${r * 0.13},${-r * 0.15} 0,0 ${-r * 0.13},${-r * 0.15}`} fill="#0f172a" />
      <polygon points={`0,${r * 0.88} ${r * 0.13},${r * 0.15} 0,0 ${-r * 0.13},${r * 0.15}`} fill="#e2e8f0" stroke="#94a3b8" strokeWidth={0.3} />
      <polygon points={`${r * 0.88},0 ${r * 0.15},${-r * 0.13} 0,0 ${r * 0.15},${r * 0.13}`} fill="#475569" />
      <polygon points={`${-r * 0.88},0 ${-r * 0.15},${-r * 0.13} 0,0 ${-r * 0.15},${r * 0.13}`} fill="#475569" />

      {/* Minor points (diagonals) */}
      <g stroke="#94a3b8" strokeWidth={0.4}>
        <line x1={0} y1={0} x2={r * 0.7} y2={-r * 0.7} />
        <line x1={0} y1={0} x2={-r * 0.7} y2={-r * 0.7} />
        <line x1={0} y1={0} x2={r * 0.7} y2={r * 0.7} />
        <line x1={0} y1={0} x2={-r * 0.7} y2={r * 0.7} />
      </g>

      {/* Labels (counter-rotated so they stay upright) */}
      <g transform={`rotate(${-rotationDeg})`}>
        <text y={-r - 5} textAnchor="middle" fontSize={10} fontWeight={700} fill="#0f172a" fontFamily="system-ui">N</text>
        <text x={r + 6} y={3} textAnchor="start" fontSize={9} fontWeight={600} fill="#475569" fontFamily="system-ui">E</text>
        <text y={r + 11} textAnchor="middle" fontSize={9} fontWeight={600} fill="#475569" fontFamily="system-ui">S</text>
        <text x={-r - 6} y={3} textAnchor="end" fontSize={9} fontWeight={600} fill="#475569" fontFamily="system-ui">O</text>
      </g>
    </g>
  );
}

/** Architectural-style scale bar "0 | 1 | 2m". */
export function ScaleBar({ x, y, scalePxPerM, meters = 5 }: {
  x: number; y: number; scalePxPerM: number; meters?: number;
}) {
  const segWidth = scalePxPerM;
  return (
    <g transform={`translate(${x}, ${y})`}>
      {/* End ticks */}
      <line x1={0} y1={-4} x2={0} y2={8} stroke="#0f172a" strokeWidth={0.8} />
      <line x1={segWidth * meters} y1={-4} x2={segWidth * meters} y2={8} stroke="#0f172a" strokeWidth={0.8} />
      {/* Segments */}
      {Array.from({ length: meters }).map((_, i) => (
        <rect
          key={i}
          x={i * segWidth}
          y={0}
          width={segWidth}
          height={4.5}
          fill={i % 2 === 0 ? "#0f172a" : "white"}
          stroke="#0f172a"
          strokeWidth={0.5}
        />
      ))}
      {/* Numbers */}
      <text x={0} y={-7} textAnchor="middle" fontSize={8.5} fill="#334155" fontFamily="system-ui">0</text>
      <text x={segWidth} y={-7} textAnchor="middle" fontSize={8.5} fill="#334155" fontFamily="system-ui">1</text>
      <text x={segWidth * 2} y={-7} textAnchor="middle" fontSize={8.5} fill="#334155" fontFamily="system-ui">2</text>
      <text x={segWidth * meters} y={-7} textAnchor="middle" fontSize={8.5} fill="#334155" fontFamily="system-ui">{meters} m</text>
    </g>
  );
}

/** Title block cartouche — bottom right of each plan. */
export function TitleBlock({
  x, y, title, subtitle, sheetCode, width = 200,
}: {
  x: number; y: number; title: string; subtitle?: string; sheetCode?: string; width?: number;
}) {
  const h = 48;
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect x={0} y={0} width={width} height={h} fill="white" stroke="#0f172a" strokeWidth={0.8} />
      <line x1={0} y1={20} x2={width} y2={20} stroke="#94a3b8" strokeWidth={0.4} />
      <line x1={width - 60} y1={20} x2={width - 60} y2={h} stroke="#94a3b8" strokeWidth={0.4} />
      <text x={8} y={14} fontSize={10.5} fontWeight={700} fill="#0f172a" fontFamily="system-ui">
        {title}
      </text>
      {subtitle && (
        <text x={8} y={34} fontSize={9} fill="#475569" fontFamily="system-ui">
          {subtitle}
        </text>
      )}
      {sheetCode && (
        <text x={width - 30} y={38} textAnchor="middle" fontSize={11} fontWeight={700} fill="#0f172a" fontFamily="system-ui">
          {sheetCode}
        </text>
      )}
      <text x={8} y={h - 4} fontSize={7} fill="#94a3b8" fontFamily="system-ui">
        ArchiClaude · SP2-v2a
      </text>
    </g>
  );
}
