"use client";

import { useEffect, useRef } from "react";
import type { Viewer } from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

// Hong Kong — plan §4.5: Cesium renders the 3D city centred on HK.
const HK_LON = 114.17;
const HK_LAT = 22.3;
const HK_ALTITUDE_M = 45_000;

/**
 * Phase-0 3D map: a navigable Cesium viewer centred on Hong Kong.
 *
 * Imagery: uses Cesium ion world imagery when NEXT_PUBLIC_CESIUM_ION_TOKEN is
 * set; otherwise falls back to plain OpenStreetMap tiles so the app runs with
 * no token. Phase 1 (step 1.1/1.2) adds the 3D building tiles and the RFZ
 * layer on top of this base.
 */
export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let viewer: Viewer | null = null;
    let cancelled = false;

    async function boot() {
      // Must be set before the cesium module is evaluated.
      (window as unknown as Record<string, unknown>).CESIUM_BASE_URL = "/cesium/";
      const Cesium = await import("cesium");
      if (cancelled || !containerRef.current) return;

      const ionToken = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN;
      let baseLayer;
      if (ionToken) {
        Cesium.Ion.defaultAccessToken = ionToken;
        baseLayer = Cesium.ImageryLayer.fromWorldImagery({});
      } else {
        baseLayer = new Cesium.ImageryLayer(
          new Cesium.OpenStreetMapImageryProvider({
            url: "https://tile.openstreetmap.org/",
          }),
        );
      }

      viewer = new Cesium.Viewer(containerRef.current, {
        baseLayer,
        baseLayerPicker: false,
        geocoder: false,
        timeline: false,
        animation: false,
        navigationHelpButton: false,
        homeButton: false,
        sceneModePicker: false,
      });

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(HK_LON, HK_LAT, HK_ALTITUDE_M),
      });
    }

    boot().catch((err) => console.error("[MapView] Cesium failed to start", err));

    return () => {
      cancelled = true;
      viewer?.destroy();
    };
  }, []);

  return <div ref={containerRef} className="absolute inset-0" />;
}
