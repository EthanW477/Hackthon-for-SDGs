"use client";

import dynamic from "next/dynamic";

// Cesium is client-only: it needs window/WebGL, so skip SSR entirely.
const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 grid place-items-center bg-slate-950 text-sm text-slate-400">
      Loading 3D map…
    </div>
  ),
});

export default function MapPanel() {
  return <MapView />;
}
