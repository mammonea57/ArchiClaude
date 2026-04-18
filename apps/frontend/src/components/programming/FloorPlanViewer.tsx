"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";

interface FloorPlanViewerProps {
  /** Raw SVG string from the API */
  svgContent: string;
  /** Called when user toggles simplified / NF complet mode */
  onModeChange?: (mode: "simplifie" | "nf_complet") => void;
}

export function FloorPlanViewer({ svgContent, onModeChange }: FloorPlanViewerProps) {
  const [scale, setScale] = useState(1);
  const [translate, setTranslate] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [mode, setMode] = useState<"simplifie" | "nf_complet">("simplifie");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  function handleWheel(e: React.WheelEvent) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    setScale((s) => Math.min(10, Math.max(0.1, s * delta)));
  }

  function handleMouseDown(e: React.MouseEvent) {
    setIsDragging(true);
    setDragStart({ x: e.clientX - translate.x, y: e.clientY - translate.y });
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!isDragging) return;
    setTranslate({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
  }

  function handleMouseUp() {
    setIsDragging(false);
  }

  function toggleMode() {
    const next = mode === "simplifie" ? "nf_complet" : "simplifie";
    setMode(next);
    onModeChange?.(next);
  }

  function resetView() {
    setScale(1);
    setTranslate({ x: 0, y: 0 });
  }

  function toggleFullscreen() {
    if (!isFullscreen) {
      containerRef.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
    setIsFullscreen((v) => !v);
  }

  return (
    <div
      ref={containerRef}
      className={[
        "relative flex flex-col border border-slate-200 rounded-lg overflow-hidden bg-white",
        isFullscreen ? "fixed inset-0 z-50 rounded-none" : "h-[480px]",
      ].join(" ")}
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-100 bg-slate-50 shrink-0">
        <Button size="sm" variant="outline" onClick={() => setScale((s) => Math.min(10, s * 1.2))}>
          +
        </Button>
        <Button size="sm" variant="outline" onClick={() => setScale((s) => Math.max(0.1, s / 1.2))}>
          −
        </Button>
        <Button size="sm" variant="outline" onClick={resetView}>
          Reset
        </Button>
        <span className="text-xs text-slate-400 tabular-nums ml-1">{(scale * 100).toFixed(0)} %</span>
        <div className="flex-1" />
        <Button size="sm" variant="outline" onClick={toggleMode}>
          {mode === "simplifie" ? "NF complet" : "Simplifié"}
        </Button>
        <Button size="sm" variant="outline" onClick={toggleFullscreen}>
          {isFullscreen ? "⤡" : "⤢"}
        </Button>
      </div>

      {/* SVG viewport */}
      <div
        className="flex-1 overflow-hidden cursor-grab active:cursor-grabbing select-none"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <div
          style={{
            transform: `translate(${translate.x}px, ${translate.y}px) scale(${scale})`,
            transformOrigin: "top left",
            width: "100%",
            height: "100%",
          }}
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
      </div>
    </div>
  );
}
