"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Compass } from "lucide-react";

export interface Photo {
  image_id: string;
  thumb_url: string;
  compass_angle: number;
}

function compassLabel(angle: number): string {
  const directions = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
  const idx = Math.round(((angle % 360) + 360) / 45) % 8;
  return directions[idx];
}

interface SitePhotosGalleryProps {
  photos: Photo[];
}

export function SitePhotosGallery({ photos }: SitePhotosGalleryProps) {
  const [selected, setSelected] = useState<Photo | null>(null);

  if (photos.length === 0) {
    return (
      <div className="rounded-xl border border-slate-100 bg-white p-10 text-center text-sm text-slate-400">
        Aucune photo de terrain disponible
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider">
          Photos de terrain
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {photos.map((photo) => (
            <button
              key={photo.image_id}
              onClick={() => setSelected(photo)}
              className="group relative rounded-xl overflow-hidden aspect-[4/3] bg-slate-100 hover:ring-2 transition-all focus:outline-none focus:ring-2"
              style={{ "--tw-ring-color": "var(--ac-primary)" } as React.CSSProperties}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={photo.thumb_url}
                alt={`Vue terrain — direction ${compassLabel(photo.compass_angle)}`}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
              />
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent px-3 py-2">
                <div className="flex items-center gap-1.5">
                  <Compass className="h-3.5 w-3.5 text-white/80" />
                  <span className="text-xs font-medium text-white">
                    {compassLabel(photo.compass_angle)}
                  </span>
                  <span className="text-xs text-white/60">
                    {Math.round(photo.compass_angle)}°
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>

      <Dialog open={selected !== null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-3xl p-0 overflow-hidden">
          <DialogHeader className="sr-only">
            <DialogTitle>
              Photo terrain — {selected ? compassLabel(selected.compass_angle) : ""}
            </DialogTitle>
          </DialogHeader>
          {selected && (
            <div className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={selected.thumb_url}
                alt={`Vue terrain direction ${compassLabel(selected.compass_angle)}`}
                className="w-full h-auto max-h-[80vh] object-contain bg-black"
              />
              <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent px-4 py-4">
                <div className="flex items-center gap-2">
                  <Compass className="h-4 w-4 text-white/80" />
                  <span className="text-sm font-medium text-white">
                    Direction {compassLabel(selected.compass_angle)} ({Math.round(selected.compass_angle)}°)
                  </span>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
