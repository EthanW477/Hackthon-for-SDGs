/**
 * Load the prebuilt Cesium bundle from /cesium/Cesium.js (copied from
 * node_modules/cesium/Build/Cesium at postinstall) instead of bundling
 * cesium/Source. The Source build pulls in Emscripten worker modules whose
 * WASM gets inlined into JS chunks as invalid template strings, breaking the
 * whole page bundle on both Turbopack and webpack production builds.
 */
import type { CesiumModule } from "./rfz";

let cesiumPromise: Promise<CesiumModule> | null = null;

export function loadCesium(): Promise<CesiumModule> {
  if (cesiumPromise) return cesiumPromise;
  cesiumPromise = new Promise<CesiumModule>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    if (w.Cesium) {
      resolve(w.Cesium as CesiumModule);
      return;
    }
    w.CESIUM_BASE_URL = "/cesium/";
    const script = document.createElement("script");
    script.src = "/cesium/Cesium.js";
    script.async = true;
    script.onload = () => resolve(w.Cesium as CesiumModule);
    script.onerror = () => reject(new Error("Failed to load /cesium/Cesium.js"));
    document.head.appendChild(script);
  });
  return cesiumPromise;
}
