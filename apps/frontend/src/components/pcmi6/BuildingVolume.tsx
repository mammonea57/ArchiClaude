"use client";
import { useMemo } from "react";
import { ExtrudeGeometry, Shape } from "three";

interface Props {
  footprint: [number, number][]; // 2D polygon in local meters (x, y)
  hauteur_m: number;
  position?: [number, number, number];
  rotation?: [number, number, number];
  color?: string;
}

export function BuildingVolume({
  footprint,
  hauteur_m,
  position = [0, 0, 0],
  rotation = [0, 0, 0],
  color = "#dddddd",
}: Props) {
  const geometry = useMemo(() => {
    const shape = new Shape();
    if (footprint.length === 0) return null;
    shape.moveTo(footprint[0][0], footprint[0][1]);
    for (let i = 1; i < footprint.length; i++) {
      shape.lineTo(footprint[i][0], footprint[i][1]);
    }
    shape.closePath();

    const extrudeSettings = {
      depth: hauteur_m,
      bevelEnabled: false,
    };

    const geom = new ExtrudeGeometry(shape, extrudeSettings);
    // Rotate so Z (extrusion axis) becomes world Y (up)
    geom.rotateX(-Math.PI / 2);
    return geom;
  }, [footprint, hauteur_m]);

  if (!geometry) return null;

  return (
    <mesh geometry={geometry} position={position} rotation={rotation} castShadow receiveShadow>
      <meshStandardMaterial color={color} roughness={0.7} metalness={0.1} />
    </mesh>
  );
}
