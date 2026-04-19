"use client";

interface Props {
  renderUrl: string;
  label: string | null;
}

export function RenderDetail({ renderUrl, label }: Props) {
  return (
    <div className="w-full">
      <h3 className="font-semibold text-slate-900 mb-2">{label || "Rendu PCMI6"}</h3>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={renderUrl} alt={label || "Rendu"} className="w-full rounded-lg" />
      <a
        href={renderUrl}
        download
        className="inline-block mt-2 text-xs text-teal-600 underline"
      >
        Télécharger
      </a>
    </div>
  );
}
