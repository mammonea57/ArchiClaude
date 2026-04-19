"use client";
import Image from "next/image";
import type { Material } from "@/lib/hooks/useMaterials";

export function MaterialCard({
  material,
  selected,
  onClick,
}: {
  material: Material;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center gap-1 rounded-lg border p-2 transition-all hover:shadow-md ${
        selected
          ? "border-teal-600 ring-2 ring-teal-500 bg-teal-50"
          : "border-slate-200 bg-white"
      }`}
      title={material.nom}
    >
      <div className="h-[100px] w-[100px] overflow-hidden rounded bg-slate-100">
        <Image
          src={material.thumbnail_url}
          alt={material.nom}
          width={100}
          height={100}
          className="object-cover"
          unoptimized
        />
      </div>
      <div className="text-center text-xs text-slate-700 w-[100px] truncate">{material.nom}</div>
    </button>
  );
}
