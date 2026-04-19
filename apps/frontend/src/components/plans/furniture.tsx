"use client";

/**
 * SVG furniture symbols used in 2D floor plans.
 * Each component is centered at (0,0); the caller translates + rotates.
 * Dimensions are in SVG pixels at the caller's scale — caller passes a
 * `scale` (px/m) and every symbol sizes itself in real-world centimeters.
 */

export interface FurnitureProps {
  scale: number; // px per meter
}

function cm(scale: number, x: number): number {
  return (x / 100) * scale;
}

/* ──────────── Living room ──────────── */

export function Sofa3p({ scale }: FurnitureProps) {
  const W = cm(scale, 220);
  const D = cm(scale, 90);
  return (
    <g>
      {/* base */}
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={6} fill="#e2e8f0" stroke="#475569" strokeWidth={0.8} />
      {/* backrest */}
      <rect x={-W / 2 + 4} y={-D / 2 + 4} width={W - 8} height={D * 0.35} rx={3} fill="#cbd5e1" />
      {/* cushions */}
      {[0, 1, 2].map((i) => (
        <rect
          key={i}
          x={-W / 2 + 8 + i * ((W - 16) / 3)}
          y={0}
          width={(W - 24) / 3}
          height={D * 0.4}
          rx={3}
          fill="#f1f5f9"
          stroke="#94a3b8"
          strokeWidth={0.4}
        />
      ))}
    </g>
  );
}

export function Armchair({ scale }: FurnitureProps) {
  const W = cm(scale, 90);
  const D = cm(scale, 90);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={4} fill="#e2e8f0" stroke="#475569" strokeWidth={0.6} />
      <rect x={-W / 2 + 4} y={-D / 2 + 4} width={W - 8} height={D * 0.35} rx={2} fill="#cbd5e1" />
      <rect x={-W / 2 + 4} y={0} width={W - 8} height={D * 0.4} rx={2} fill="#f1f5f9" stroke="#94a3b8" strokeWidth={0.3} />
    </g>
  );
}

export function CoffeeTable({ scale }: FurnitureProps) {
  const W = cm(scale, 120);
  const D = cm(scale, 60);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={3} fill="white" stroke="#64748b" strokeWidth={0.6} />
      <rect x={-W / 2 + 4} y={-D / 2 + 4} width={W - 8} height={D - 8} rx={2} fill="none" stroke="#cbd5e1" strokeWidth={0.4} />
    </g>
  );
}

export function DiningTable({ scale, seats = 6 }: FurnitureProps & { seats?: number }) {
  const W = cm(scale, seats >= 8 ? 220 : seats >= 6 ? 180 : 140);
  const D = cm(scale, 90);
  const chairSize = cm(scale, 45);
  const gap = cm(scale, 10);
  const nPerSide = Math.floor(seats / 2);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={4} fill="#fafaf9" stroke="#475569" strokeWidth={0.7} />
      {/* wood grain hint */}
      <line x1={-W / 2 + 6} y1={0} x2={W / 2 - 6} y2={0} stroke="#cbd5e1" strokeWidth={0.3} />
      {/* chairs top + bottom */}
      {Array.from({ length: nPerSide }).map((_, i) => {
        const xPos = -W / 2 + ((i + 0.5) * W) / nPerSide;
        return (
          <g key={i}>
            <rect x={xPos - chairSize / 2} y={-D / 2 - gap - chairSize} width={chairSize} height={chairSize} rx={3} fill="#f1f5f9" stroke="#94a3b8" strokeWidth={0.4} />
            <rect x={xPos - chairSize / 2} y={D / 2 + gap} width={chairSize} height={chairSize} rx={3} fill="#f1f5f9" stroke="#94a3b8" strokeWidth={0.4} />
          </g>
        );
      })}
    </g>
  );
}

export function TvUnit({ scale }: FurnitureProps) {
  const W = cm(scale, 200);
  const D = cm(scale, 40);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} fill="#1e293b" stroke="#0f172a" strokeWidth={0.5} />
      <rect x={-W / 2 + 4} y={-D / 2 + 4} width={W - 8} height={D - 8} fill="#334155" />
      <rect x={-W / 6} y={-D / 2 - cm(scale, 8)} width={cm(scale, 70)} height={cm(scale, 5)} fill="#0f172a" />
    </g>
  );
}

/* ──────────── Bedroom ──────────── */

export function Bed({ scale, size = "queen" }: FurnitureProps & { size?: "single" | "double" | "queen" | "king" }) {
  const widths: Record<string, number> = { single: 90, double: 140, queen: 160, king: 180 };
  const W = cm(scale, widths[size] ?? 160);
  const L = cm(scale, 200);
  return (
    <g>
      {/* frame */}
      <rect x={-W / 2} y={-L / 2} width={W} height={L} rx={3} fill="#f1f5f9" stroke="#475569" strokeWidth={0.8} />
      {/* headboard */}
      <rect x={-W / 2 - cm(scale, 3)} y={-L / 2 - cm(scale, 8)} width={W + cm(scale, 6)} height={cm(scale, 12)} rx={2} fill="#cbd5e1" stroke="#64748b" strokeWidth={0.5} />
      {/* pillows (2) */}
      <rect x={-W / 2 + cm(scale, 5)} y={-L / 2 + cm(scale, 5)} width={(W - cm(scale, 15)) / 2} height={cm(scale, 25)} rx={3} fill="white" stroke="#94a3b8" strokeWidth={0.4} />
      <rect x={cm(scale, 2.5)} y={-L / 2 + cm(scale, 5)} width={(W - cm(scale, 15)) / 2} height={cm(scale, 25)} rx={3} fill="white" stroke="#94a3b8" strokeWidth={0.4} />
      {/* blanket diagonal (folded corner) */}
      <path
        d={`M ${-W / 2 + 2} ${L / 2 - cm(scale, 40)} L ${W / 2 - 2} ${L / 2 - cm(scale, 40)}`}
        stroke="#94a3b8"
        strokeWidth={0.6}
        strokeDasharray="3 2"
      />
      <path
        d={`M ${-W / 2 + 2} ${L / 2 - cm(scale, 40)} L ${-cm(scale, 10)} ${L / 2 - cm(scale, 25)} L ${-W / 2 + 2} ${L / 2 - cm(scale, 20)} Z`}
        fill="#e2e8f0"
        stroke="#94a3b8"
        strokeWidth={0.4}
      />
      {/* bedside tables */}
      <rect x={-W / 2 - cm(scale, 45)} y={-L / 2 + cm(scale, 5)} width={cm(scale, 40)} height={cm(scale, 40)} fill="white" stroke="#64748b" strokeWidth={0.5} />
      <circle cx={-W / 2 - cm(scale, 25)} cy={-L / 2 + cm(scale, 25)} r={cm(scale, 8)} fill="#fef3c7" stroke="#d97706" strokeWidth={0.4} />
      <rect x={W / 2 + cm(scale, 5)} y={-L / 2 + cm(scale, 5)} width={cm(scale, 40)} height={cm(scale, 40)} fill="white" stroke="#64748b" strokeWidth={0.5} />
      <circle cx={W / 2 + cm(scale, 25)} cy={-L / 2 + cm(scale, 25)} r={cm(scale, 8)} fill="#fef3c7" stroke="#d97706" strokeWidth={0.4} />
    </g>
  );
}

export function Wardrobe({ scale, widthCm = 180 }: FurnitureProps & { widthCm?: number }) {
  const W = cm(scale, widthCm);
  const D = cm(scale, 60);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} fill="#64748b" stroke="#0f172a" strokeWidth={0.8} />
      <rect x={-W / 2 + 2} y={-D / 2 + 2} width={W - 4} height={D - 4} fill="#94a3b8" />
      {/* door divisions */}
      {Array.from({ length: Math.ceil(widthCm / 60) }).map((_, i) => (
        <line
          key={i}
          x1={-W / 2 + ((i + 1) * W) / Math.ceil(widthCm / 60)}
          y1={-D / 2 + 2}
          x2={-W / 2 + ((i + 1) * W) / Math.ceil(widthCm / 60)}
          y2={D / 2 - 2}
          stroke="#475569"
          strokeWidth={0.4}
        />
      ))}
    </g>
  );
}

export function Desk({ scale }: FurnitureProps) {
  const W = cm(scale, 120);
  const D = cm(scale, 60);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={2} fill="#fafaf9" stroke="#475569" strokeWidth={0.6} />
      {/* chair */}
      <rect x={-cm(scale, 22)} y={D / 2 + cm(scale, 5)} width={cm(scale, 45)} height={cm(scale, 45)} rx={5} fill="#e2e8f0" stroke="#64748b" strokeWidth={0.5} />
    </g>
  );
}

/* ──────────── Kitchen ──────────── */

export function KitchenLinear({ scale, lengthCm = 300 }: FurnitureProps & { lengthCm?: number }) {
  const W = cm(scale, lengthCm);
  const D = cm(scale, 65);
  return (
    <g>
      {/* counter */}
      <rect x={-W / 2} y={-D / 2} width={W} height={D} fill="#f1f5f9" stroke="#334155" strokeWidth={0.8} />
      {/* back strip (wall cabinets) */}
      <rect x={-W / 2} y={-D / 2} width={W} height={cm(scale, 10)} fill="#cbd5e1" />

      {/* sink */}
      <rect
        x={-W / 2 + cm(scale, 20)}
        y={-D / 2 + cm(scale, 18)}
        width={cm(scale, 60)}
        height={cm(scale, 40)}
        rx={3}
        fill="#e2e8f0"
        stroke="#475569"
        strokeWidth={0.6}
      />
      <rect
        x={-W / 2 + cm(scale, 25)}
        y={-D / 2 + cm(scale, 22)}
        width={cm(scale, 50)}
        height={cm(scale, 32)}
        rx={2}
        fill="white"
        stroke="#94a3b8"
        strokeWidth={0.4}
      />
      {/* tap */}
      <circle cx={-W / 2 + cm(scale, 50)} cy={-D / 2 + cm(scale, 14)} r={cm(scale, 3)} fill="#475569" />

      {/* hob */}
      <rect
        x={-W / 2 + cm(scale, 100)}
        y={-D / 2 + cm(scale, 18)}
        width={cm(scale, 60)}
        height={cm(scale, 60)}
        fill="#1e293b"
        stroke="#0f172a"
        strokeWidth={0.6}
      />
      {[[120, 32], [150, 32], [120, 62], [150, 62]].map(([dx, dy], i) => (
        <circle
          key={i}
          cx={-W / 2 + cm(scale, dx)}
          cy={-D / 2 + cm(scale, dy)}
          r={cm(scale, 10)}
          fill="none"
          stroke="#cbd5e1"
          strokeWidth={0.8}
        />
      ))}

      {/* oven door lines */}
      <line x1={-W / 2 + cm(scale, 100)} y1={-D / 2 + cm(scale, 78)} x2={-W / 2 + cm(scale, 160)} y2={-D / 2 + cm(scale, 78)} stroke="#0f172a" strokeWidth={0.5} />

      {/* fridge */}
      <rect
        x={-W / 2 + cm(scale, 180)}
        y={-D / 2 + cm(scale, 10)}
        width={cm(scale, 60)}
        height={D - cm(scale, 15)}
        fill="white"
        stroke="#475569"
        strokeWidth={0.7}
      />
      <line x1={-W / 2 + cm(scale, 180)} y1={-D / 2 + cm(scale, 30)} x2={-W / 2 + cm(scale, 240)} y2={-D / 2 + cm(scale, 30)} stroke="#94a3b8" strokeWidth={0.4} />

      {/* base cabinet lines */}
      {lengthCm > 250 && (
        <line x1={-W / 2 + cm(scale, 250)} y1={-D / 2 + cm(scale, 10)} x2={-W / 2 + cm(scale, 250)} y2={D / 2} stroke="#475569" strokeWidth={0.5} strokeDasharray="2 2" />
      )}
    </g>
  );
}

export function KitchenIsland({ scale }: FurnitureProps) {
  const W = cm(scale, 200);
  const D = cm(scale, 90);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={3} fill="#f8fafc" stroke="#334155" strokeWidth={0.7} />
      {/* bar stools */}
      {[-60, 0, 60].map((dx) => (
        <circle key={dx} cx={cm(scale, dx)} cy={D / 2 + cm(scale, 30)} r={cm(scale, 12)} fill="#e2e8f0" stroke="#64748b" strokeWidth={0.4} />
      ))}
    </g>
  );
}

/* ──────────── Bathroom ──────────── */

export function Bathtub({ scale }: FurnitureProps) {
  const W = cm(scale, 170);
  const D = cm(scale, 75);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={8} fill="#dbeafe" stroke="#0369a1" strokeWidth={0.8} />
      <rect x={-W / 2 + cm(scale, 5)} y={-D / 2 + cm(scale, 5)} width={W - cm(scale, 10)} height={D - cm(scale, 10)} rx={6} fill="white" stroke="#93c5fd" strokeWidth={0.5} />
      {/* drain */}
      <circle cx={W / 2 - cm(scale, 25)} cy={0} r={cm(scale, 4)} fill="none" stroke="#475569" strokeWidth={0.4} />
      {/* tap */}
      <rect x={-W / 2 - cm(scale, 3)} y={-cm(scale, 8)} width={cm(scale, 6)} height={cm(scale, 16)} fill="#94a3b8" />
    </g>
  );
}

export function ShowerStall({ scale }: FurnitureProps) {
  const W = cm(scale, 90);
  const D = cm(scale, 90);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} fill="#e0f2fe" stroke="#0369a1" strokeWidth={0.8} />
      {/* glass door */}
      <line x1={-W / 2} y1={D / 2} x2={W / 2} y2={D / 2} stroke="#0369a1" strokeWidth={1.5} />
      {/* diagonal flow lines */}
      <path d={`M ${-W / 2 + 4} ${-D / 2 + 4} L ${W / 2 - 4} ${D / 2 - 4} M ${W / 2 - 4} ${-D / 2 + 4} L ${-W / 2 + 4} ${D / 2 - 4}`} stroke="#7dd3fc" strokeWidth={0.4} />
      {/* drain */}
      <circle cx={0} cy={0} r={cm(scale, 3)} fill="none" stroke="#475569" strokeWidth={0.4} />
    </g>
  );
}

export function Washbasin({ scale }: FurnitureProps) {
  const W = cm(scale, 80);
  const D = cm(scale, 50);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} rx={4} fill="white" stroke="#475569" strokeWidth={0.7} />
      <ellipse cx={0} cy={0} rx={cm(scale, 28)} ry={cm(scale, 16)} fill="#e0f2fe" stroke="#0369a1" strokeWidth={0.5} />
      <circle cx={0} cy={0} r={cm(scale, 2)} fill="none" stroke="#475569" strokeWidth={0.4} />
      <rect x={-cm(scale, 3)} y={-D / 2 - cm(scale, 4)} width={cm(scale, 6)} height={cm(scale, 10)} fill="#94a3b8" />
    </g>
  );
}

export function Toilet({ scale }: FurnitureProps) {
  const W = cm(scale, 45);
  const L = cm(scale, 65);
  return (
    <g>
      {/* tank */}
      <rect x={-W / 2} y={-L / 2} width={W} height={cm(scale, 20)} rx={2} fill="#e2e8f0" stroke="#64748b" strokeWidth={0.5} />
      {/* bowl */}
      <ellipse cx={0} cy={L / 2 - cm(scale, 22)} rx={W / 2 - cm(scale, 2)} ry={cm(scale, 22)} fill="white" stroke="#475569" strokeWidth={0.7} />
      <ellipse cx={0} cy={L / 2 - cm(scale, 22)} rx={W / 2 - cm(scale, 8)} ry={cm(scale, 16)} fill="#e0f2fe" stroke="#94a3b8" strokeWidth={0.4} />
    </g>
  );
}

/* ──────────── Storage ──────────── */

export function StorageUnit({ scale, widthCm = 120, depthCm = 60 }: FurnitureProps & { widthCm?: number; depthCm?: number }) {
  const W = cm(scale, widthCm);
  const D = cm(scale, depthCm);
  return (
    <g>
      <rect x={-W / 2} y={-D / 2} width={W} height={D} fill="#94a3b8" stroke="#0f172a" strokeWidth={0.6} />
      <line x1={-W / 2} y1={-D / 2} x2={W / 2} y2={D / 2} stroke="#475569" strokeWidth={0.3} />
      <line x1={W / 2} y1={-D / 2} x2={-W / 2} y2={D / 2} stroke="#475569" strokeWidth={0.3} />
    </g>
  );
}

/* ──────────── Outdoor ──────────── */

export function PatioTable({ scale }: FurnitureProps) {
  const R = cm(scale, 45);
  return (
    <g>
      <circle cx={0} cy={0} r={R} fill="white" stroke="#64748b" strokeWidth={0.5} />
      <circle cx={0} cy={0} r={R - cm(scale, 4)} fill="none" stroke="#cbd5e1" strokeWidth={0.3} />
      {/* 4 chairs around */}
      {[0, 90, 180, 270].map((angle) => {
        const rad = (angle * Math.PI) / 180;
        const dx = Math.cos(rad) * (R + cm(scale, 20));
        const dy = Math.sin(rad) * (R + cm(scale, 20));
        return (
          <circle key={angle} cx={dx} cy={dy} r={cm(scale, 15)} fill="#e2e8f0" stroke="#64748b" strokeWidth={0.4} />
        );
      })}
    </g>
  );
}

export function PottedPlant({ scale, size = "M" }: FurnitureProps & { size?: "S" | "M" | "L" }) {
  const r = size === "L" ? cm(scale, 30) : size === "M" ? cm(scale, 22) : cm(scale, 14);
  return (
    <g>
      <circle cx={0} cy={0} r={r * 0.55} fill="#d6a45a" stroke="#92400e" strokeWidth={0.4} />
      <circle cx={-r * 0.2} cy={-r * 0.15} r={r * 0.4} fill="#4ea055" stroke="#2f7a35" strokeWidth={0.4} />
      <circle cx={r * 0.25} cy={-r * 0.05} r={r * 0.45} fill="#6bbe70" stroke="#2f7a35" strokeWidth={0.4} />
      <circle cx={0} cy={r * 0.2} r={r * 0.35} fill="#58af5f" stroke="#2f7a35" strokeWidth={0.4} />
    </g>
  );
}
