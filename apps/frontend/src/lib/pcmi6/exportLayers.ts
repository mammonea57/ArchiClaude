import * as THREE from "three";

/**
 * Render the scene with different materials to produce mask/normal/depth PNGs.
 * Returns PNG blobs for each layer.
 */
export async function exportLayers(
  gl: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  volumeGroup: THREE.Object3D,
): Promise<{ mask: Blob; normal: Blob; depth: Blob }> {
  const originalMaterials = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();

  volumeGroup.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      const mesh = obj as THREE.Mesh;
      originalMaterials.set(mesh, mesh.material);
    }
  });

  // 1. Mask pass — white volume on black background
  const maskMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff });
  volumeGroup.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      (obj as THREE.Mesh).material = maskMaterial;
    }
  });
  const originalBg = scene.background;
  scene.background = new THREE.Color(0x000000);
  gl.render(scene, camera);
  const maskBlob = await canvasToBlob(gl.domElement);

  // 2. Normal pass
  const normalMaterial = new THREE.MeshNormalMaterial();
  volumeGroup.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      (obj as THREE.Mesh).material = normalMaterial;
    }
  });
  scene.background = new THREE.Color(0x7f7fff);
  gl.render(scene, camera);
  const normalBlob = await canvasToBlob(gl.domElement);

  // 3. Depth pass
  const depthMaterial = new THREE.MeshDepthMaterial();
  volumeGroup.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      (obj as THREE.Mesh).material = depthMaterial;
    }
  });
  scene.background = new THREE.Color(0xffffff);
  gl.render(scene, camera);
  const depthBlob = await canvasToBlob(gl.domElement);

  // Restore
  volumeGroup.traverse((obj) => {
    if ((obj as THREE.Mesh).isMesh) {
      const mesh = obj as THREE.Mesh;
      const orig = originalMaterials.get(mesh);
      if (orig) mesh.material = orig;
    }
  });
  scene.background = originalBg;

  return { mask: maskBlob, normal: normalBlob, depth: depthBlob };
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("Canvas toBlob failed"));
    }, "image/png");
  });
}
