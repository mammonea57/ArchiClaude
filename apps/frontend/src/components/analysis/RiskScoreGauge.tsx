"use client";

interface RiskScoreGaugeProps {
  score: number; // 0-100
  justification?: string;
}

function getColor(score: number): string {
  if (score < 30) return "#22c55e"; // green
  if (score < 60) return "#eab308"; // yellow
  if (score < 80) return "#f97316"; // orange
  return "#ef4444"; // red
}

function getLabel(score: number): string {
  if (score < 30) return "Risque faible";
  if (score < 60) return "Risque modéré";
  if (score < 80) return "Risque élevé";
  return "Risque critique";
}

export function RiskScoreGauge({ score, justification }: RiskScoreGaugeProps) {
  const clampedScore = Math.max(0, Math.min(100, score));
  const color = getColor(clampedScore);
  const label = getLabel(clampedScore);

  // SVG circle arc parameters
  const radius = 40;
  const cx = 60;
  const cy = 60;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - clampedScore / 100);

  return (
    <div className="flex flex-col items-center gap-3 p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="relative">
        <svg width="120" height="120" viewBox="0 0 120 120">
          {/* Background track */}
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth="10"
          />
          {/* Score arc */}
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            transform={`rotate(-90 ${cx} ${cy})`}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
          {/* Score text */}
          <text
            x={cx}
            y={cy}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize="22"
            fontWeight="700"
            fill={color}
          >
            {clampedScore}
          </text>
          {/* /100 subscript */}
          <text
            x={cx}
            y={cy + 16}
            textAnchor="middle"
            fontSize="10"
            fill="#9ca3af"
          >
            /100
          </text>
        </svg>
      </div>

      <div className="text-center">
        <span
          className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold text-white"
          style={{ backgroundColor: color }}
        >
          {label}
        </span>
      </div>

      {justification && (
        <p className="text-xs text-gray-600 text-center max-w-xs leading-relaxed">
          {justification}
        </p>
      )}
    </div>
  );
}
