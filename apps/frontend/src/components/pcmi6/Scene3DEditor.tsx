"use client";
import { Suspense, useRef } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, TransformControls } from "@react-three/drei";
import * as THREE from "three";
import { BuildingVolume } from "./BuildingVolume";

interface Props {
  photoUrl: string;
  footprint: [number, number][];
  hauteur_m: number;
  cameraPosition: [number, number, number];
  cameraFov: number;
  volumePosition: [number, number, number];
  volumeRotation: [number, number, number];
  transformMode: "translate" | "rotate";
  onVolumeChange: (pos: [number, number, number], rot: [number, number, number]) => void;
}

export function Scene3DEditor({
  photoUrl,
  footprint,
  hauteur_m,
  cameraPosition,
  cameraFov,
  volumePosition,
  volumeRotation,
  transformMode,
  onVolumeChange,
}: Props) {
  const volumeRef = useRef<THREE.Mesh>(null);

  return (
    <div className="w-full h-full relative">
      {/* Background photo */}
      <div
        className="absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: `url('${photoUrl}')` }}
      />

      {/* 3D canvas on top, transparent background */}
      <Canvas
        shadows
        camera={{ position: cameraPosition, fov: cameraFov }}
        style={{ position: "absolute", inset: 0, background: "transparent" }}
        gl={{ alpha: true, preserveDrawingBuffer: true }}
      >
        <Suspense fallback={null}>
          <ambientLight intensity={0.6} />
          <directionalLight
            position={[10, 20, 10]}
            intensity={0.8}
            castShadow
            shadow-mapSize={[1024, 1024]}
          />

          {/* Ground plane for shadow */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
            <planeGeometry args={[200, 200]} />
            <shadowMaterial opacity={0.3} />
          </mesh>

          <group position={volumePosition} rotation={volumeRotation}>
            <BuildingVolume footprint={footprint} hauteur_m={hauteur_m} />
          </group>

          {volumeRef.current && (
            <TransformControls
              object={volumeRef.current}
              mode={transformMode}
              onObjectChange={() => {
                const pos = volumeRef.current!.position;
                const rot = volumeRef.current!.rotation;
                onVolumeChange([pos.x, pos.y, pos.z], [rot.x, rot.y, rot.z]);
              }}
            />
          )}

          <OrbitControls makeDefault enablePan enableZoom enableRotate />
        </Suspense>
      </Canvas>
    </div>
  );
}
