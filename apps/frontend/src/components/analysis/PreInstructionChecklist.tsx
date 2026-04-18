"use client";

import { useState } from "react";

interface ChecklistItem {
  demarche: string;
  timing_jours: number;
  priorite: string;
  raison: string;
}

interface PreInstructionChecklistProps {
  items: ChecklistItem[];
}

function getTimingLabel(days: number): string {
  return `J-${days}`;
}

function getPrioriteStyle(priorite: string): {
  bg: string;
  text: string;
  border: string;
} {
  switch (priorite) {
    case "obligatoire":
      return {
        bg: "bg-red-50",
        text: "text-red-700",
        border: "border-red-200",
      };
    case "fortement_recommande":
      return {
        bg: "bg-orange-50",
        text: "text-orange-700",
        border: "border-orange-200",
      };
    default:
      return {
        bg: "bg-blue-50",
        text: "text-blue-700",
        border: "border-blue-200",
      };
  }
}

function getPrioriteLabel(priorite: string): string {
  switch (priorite) {
    case "obligatoire":
      return "Obligatoire";
    case "fortement_recommande":
      return "Fortement recommandé";
    default:
      return "Recommandé";
  }
}

function getTimingBadgeStyle(days: number): string {
  if (days >= 75) return "bg-purple-100 text-purple-700";
  if (days >= 45) return "bg-blue-100 text-blue-700";
  if (days >= 30) return "bg-teal-100 text-teal-700";
  return "bg-gray-100 text-gray-600";
}

export function PreInstructionChecklist({ items }: PreInstructionChecklistProps) {
  const [checked, setChecked] = useState<Record<number, boolean>>({});

  // Sort by timing_jours descending (J-90 first)
  const sorted = [...items].sort((a, b) => b.timing_jours - a.timing_jours);

  const toggleItem = (idx: number) => {
    setChecked((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const doneCount = Object.values(checked).filter(Boolean).length;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">
          Démarches pré-instruction
        </h3>
        <span className="text-xs text-gray-500">
          {doneCount}/{sorted.length} effectuées
        </span>
      </div>

      {/* Progress bar */}
      <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-green-500 rounded-full transition-all duration-300"
          style={{ width: `${sorted.length > 0 ? (doneCount / sorted.length) * 100 : 0}%` }}
        />
      </div>

      <div className="flex flex-col gap-2">
        {sorted.map((item, idx) => {
          const isChecked = checked[idx] ?? false;
          const prioStyle = getPrioriteStyle(item.priorite);
          const timingStyle = getTimingBadgeStyle(item.timing_jours);

          return (
            <div
              key={idx}
              className={`flex items-start gap-3 p-3 rounded-lg border transition-opacity ${
                isChecked ? "opacity-50" : ""
              } ${prioStyle.bg} ${prioStyle.border}`}
            >
              {/* Checkbox */}
              <button
                type="button"
                onClick={() => toggleItem(idx)}
                className={`mt-0.5 w-4 h-4 flex-shrink-0 rounded border-2 flex items-center justify-center transition-colors ${
                  isChecked
                    ? "bg-green-500 border-green-500"
                    : "bg-white border-gray-300 hover:border-green-400"
                }`}
                aria-label={isChecked ? "Marquer comme non effectué" : "Marquer comme effectué"}
              >
                {isChecked && (
                  <svg
                    className="w-2.5 h-2.5 text-white"
                    fill="none"
                    viewBox="0 0 10 10"
                  >
                    <path
                      d="M1.5 5l2.5 2.5 4.5-4.5"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </button>

              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-0.5">
                  <p
                    className={`text-sm font-medium ${prioStyle.text} ${
                      isChecked ? "line-through" : ""
                    }`}
                  >
                    {item.demarche}
                  </p>
                </div>

                <div className="flex flex-wrap gap-1.5 mt-1">
                  {/* Timing badge */}
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded-full ${timingStyle}`}
                  >
                    {getTimingLabel(item.timing_jours)}
                  </span>
                  {/* Priority badge */}
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${prioStyle.bg} ${prioStyle.text} border ${prioStyle.border}`}
                  >
                    {getPrioriteLabel(item.priorite)}
                  </span>
                </div>

                {item.raison && (
                  <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                    {item.raison}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
