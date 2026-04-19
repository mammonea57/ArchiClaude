"use client";
import { Label } from "@/components/ui/label";

interface Props {
  heightM: number;
  pitchDeg: number;
  focalMm: number;
  rotDeg: number;
  onChange: (next: { heightM: number; pitchDeg: number; focalMm: number; rotDeg: number }) => void;
  onReset: () => void;
}

export function CameraCalibrator({ heightM, pitchDeg, focalMm, rotDeg, onChange, onReset }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <Field label={`Hauteur caméra: ${heightM.toFixed(1)} m`}>
        <input
          type="range"
          min={1.5}
          max={10}
          step={0.1}
          value={heightM}
          onChange={(e) =>
            onChange({ heightM: parseFloat(e.target.value), pitchDeg, focalMm, rotDeg })
          }
          className="w-full"
        />
      </Field>
      <Field label={`Inclinaison: ${pitchDeg.toFixed(1)}°`}>
        <input
          type="range"
          min={-20}
          max={20}
          step={0.5}
          value={pitchDeg}
          onChange={(e) =>
            onChange({ heightM, pitchDeg: parseFloat(e.target.value), focalMm, rotDeg })
          }
          className="w-full"
        />
      </Field>
      <Field label={`Focale: ${focalMm} mm`}>
        <input
          type="range"
          min={35}
          max={85}
          step={1}
          value={focalMm}
          onChange={(e) =>
            onChange({ heightM, pitchDeg, focalMm: parseInt(e.target.value), rotDeg })
          }
          className="w-full"
        />
      </Field>
      <Field label={`Rotation horizontale: ${rotDeg.toFixed(1)}°`}>
        <input
          type="range"
          min={-30}
          max={30}
          step={0.5}
          value={rotDeg}
          onChange={(e) =>
            onChange({ heightM, pitchDeg, focalMm, rotDeg: parseFloat(e.target.value) })
          }
          className="w-full"
        />
      </Field>
      <button
        onClick={onReset}
        className="text-xs text-teal-600 hover:underline self-start"
      >
        Réinitialiser calibration auto
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-slate-600">{label}</Label>
      {children}
    </div>
  );
}
