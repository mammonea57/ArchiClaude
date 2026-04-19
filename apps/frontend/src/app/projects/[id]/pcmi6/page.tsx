"use client";
import { use, useState } from "react";
import Link from "next/link";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Scene3DEditor } from "@/components/pcmi6/Scene3DEditor";
import { CameraCalibrator } from "@/components/pcmi6/CameraCalibrator";
import { MaterialsPicker } from "@/components/pcmi6/MaterialsPicker";
import { RenderTrigger } from "@/components/pcmi6/RenderTrigger";
import { RendersGallery } from "@/components/pcmi6/RendersGallery";

export default function Pcmi6Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  // Placeholder state — real values wired from project data
  const [heightM, setHeightM] = useState(2.5);
  const [pitchDeg, setPitchDeg] = useState(0);
  const [focalMm, setFocalMm] = useState(50);
  const [rotDeg, setRotDeg] = useState(0);
  const [currentSurface, setCurrentSurface] = useState("facade");
  const [materialsConfig, setMaterialsConfig] = useState<Record<string, string>>({});

  // Placeholder volume data
  const footprint: [number, number][] = [
    [-5, -5],
    [5, -5],
    [5, 5],
    [-5, 5],
  ];
  const hauteur_m = 9;
  const photoUrl = "/placeholder-photo.jpg"; // wired from project
  const cameraConfig = {
    lat: 48.85,
    lng: 2.35,
    heading: 90,
    pitch: pitchDeg,
    fov: 60,
  };

  return (
    <main className="h-screen flex flex-col">
      <nav className="border-b border-slate-100 bg-white px-6 py-3 shrink-0">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-lg font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <div className="flex gap-4 text-sm text-slate-500">
            <Link href="/projects" className="hover:text-slate-700">Projets</Link>
            <Link href={`/projects/${id}`} className="hover:text-slate-700">Projet</Link>
            <Link href={`/projects/${id}/pcmi`} className="hover:text-slate-700">Dossier PC</Link>
          </div>
        </div>
      </nav>

      <div className="flex-1 grid grid-cols-[1fr_400px] min-h-0">
        {/* Left: 3D editor */}
        <div className="relative">
          <Scene3DEditor
            photoUrl={photoUrl}
            footprint={footprint}
            hauteur_m={hauteur_m}
            cameraPosition={[0, heightM, -15]}
            cameraFov={60}
            volumePosition={[0, 0, 0]}
            volumeRotation={[0, (rotDeg * Math.PI) / 180, 0]}
            transformMode="translate"
            onVolumeChange={() => {}}
          />
        </div>

        {/* Right: controls */}
        <aside className="border-l border-slate-200 bg-white overflow-y-auto p-4">
          <h1 className="font-display text-xl font-bold text-slate-900 mb-3">PCMI6</h1>
          <p className="text-xs text-slate-500 mb-4">
            Insertion paysagère — placez le volume sur la photo et choisissez les matériaux
          </p>

          <Tabs defaultValue="camera">
            <TabsList className="grid grid-cols-3 w-full mb-3">
              <TabsTrigger value="camera" className="text-xs">Caméra</TabsTrigger>
              <TabsTrigger value="materials" className="text-xs">Matériaux</TabsTrigger>
              <TabsTrigger value="render" className="text-xs">Rendu</TabsTrigger>
            </TabsList>

            <TabsContent value="camera">
              <CameraCalibrator
                heightM={heightM}
                pitchDeg={pitchDeg}
                focalMm={focalMm}
                rotDeg={rotDeg}
                onChange={({ heightM: h, pitchDeg: p, focalMm: f, rotDeg: r }) => {
                  setHeightM(h);
                  setPitchDeg(p);
                  setFocalMm(f);
                  setRotDeg(r);
                }}
                onReset={() => {
                  setHeightM(2.5);
                  setPitchDeg(0);
                  setFocalMm(50);
                  setRotDeg(0);
                }}
              />
            </TabsContent>

            <TabsContent value="materials">
              <div className="flex gap-1 mb-2">
                {["facade", "toiture", "menuiseries"].map((s) => (
                  <button
                    key={s}
                    onClick={() => setCurrentSurface(s)}
                    className={`px-2 py-1 text-xs rounded ${
                      currentSurface === s ? "bg-teal-600 text-white" : "bg-slate-100"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <MaterialsPicker
                value={materialsConfig}
                onChange={setMaterialsConfig}
                currentSurface={currentSurface}
              />
            </TabsContent>

            <TabsContent value="render">
              <RenderTrigger
                projectId={id}
                materialsConfig={materialsConfig}
                cameraConfig={cameraConfig}
                photoSource="mapillary"
                photoSourceId="placeholder"
                photoBaseUrl={photoUrl}
                exportLayers={async () => {
                  // Placeholder — wire to Scene3DEditor's canvas ref in v2
                  throw new Error("Layer export not wired yet — use Scene3DEditor canvas ref");
                }}
              />

              <div className="mt-6">
                <h3 className="font-semibold text-sm text-slate-700 mb-2">Historique</h3>
                <RendersGallery projectId={id} />
              </div>
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </main>
  );
}
