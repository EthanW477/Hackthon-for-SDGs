"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CustomDataSource, Viewer } from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { checkFlightPlan, type FlightPlanCheckResponse } from "@/lib/api";
import { loadRfzLayer, type CesiumModule } from "@/lib/rfz";
import { RouteDrawer } from "@/lib/route-drawer";
import MapToolbar from "./MapToolbar";
import VerdictCard from "./VerdictCard";

// Hong Kong — plan §4.5: Cesium renders the 3D city centred on HK.
const HK_LON = 114.17;
const HK_LAT = 22.3;
const HK_ALTITUDE_M = 45_000;
// Sha Tin — the demo area where the sample RFZ polygons sit.
const SHA_TIN_LON = 114.19;
const SHA_TIN_LAT = 22.38;
const SHA_TIN_ALTITUDE_M = 12_000;

/**
 * 3D map: a navigable Cesium viewer centred on Hong Kong, plus
 *  - the RFZ overlay (red, semi-transparent, toggleable — plan step 1.2)
 *  - the route drawing tool with verdict annotation (plan step 2.3)
 *
 * Imagery: uses Cesium ion world imagery when NEXT_PUBLIC_CESIUM_ION_TOKEN is
 * set; otherwise falls back to plain OpenStreetMap tiles so the app runs with
 * no token.
 */
export default function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const cesiumRef = useRef<CesiumModule | null>(null);
  const drawerRef = useRef<RouteDrawer | null>(null);
  const rfzRef = useRef<CustomDataSource | null>(null);

  const [ready, setReady] = useState(false);
  const [rfzVisible, setRfzVisible] = useState(true);
  const [rfzError, setRfzError] = useState<string | null>(null);
  const [drawActive, setDrawActive] = useState(false);
  const [pointCount, setPointCount] = useState(0);
  const [altitudeFt, setAltitudeFt] = useState(250);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<FlightPlanCheckResponse | null>(null);
  const [verdictCardOpen, setVerdictCardOpen] = useState(false);

  useEffect(() => {
    let viewer: Viewer | null = null;
    let cancelled = false;

    async function boot() {
      // Must be set before the cesium module is evaluated.
      (window as unknown as Record<string, unknown>).CESIUM_BASE_URL = "/cesium/";
      const Cesium = await import("cesium");
      if (cancelled || !containerRef.current) return;
      cesiumRef.current = Cesium;

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
      viewerRef.current = viewer;

      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(HK_LON, HK_LAT, HK_ALTITUDE_M),
      });

      drawerRef.current = new RouteDrawer(Cesium, viewer, setPointCount);

      try {
        rfzRef.current = await loadRfzLayer(Cesium, viewer);
      } catch (err) {
        setRfzError(err instanceof Error ? err.message : "unknown error");
      }
      if (!cancelled) setReady(true);
    }

    boot().catch((err) => console.error("[MapView] Cesium failed to start", err));

    return () => {
      cancelled = true;
      drawerRef.current?.destroy();
      drawerRef.current = null;
      viewerRef.current = null;
      rfzRef.current = null;
      viewer?.destroy();
    };
  }, []);

  useEffect(() => {
    if (rfzRef.current) rfzRef.current.show = rfzVisible;
  }, [rfzVisible, ready]);

  useEffect(() => {
    drawerRef.current?.setActive(drawActive);
  }, [drawActive, ready]);

  useEffect(() => {
    drawerRef.current?.setAltitudeFt(altitudeFt);
  }, [altitudeFt, ready]);

  const handleRfzToggle = useCallback(
    (visible: boolean) => {
      setRfzVisible(visible);
      // First toggle-on is the demo moment: fly to the Sha Tin sample zones.
      if (visible && viewerRef.current && cesiumRef.current) {
        viewerRef.current.camera.flyTo({
          destination: cesiumRef.current.Cartesian3.fromDegrees(
            SHA_TIN_LON,
            SHA_TIN_LAT,
            SHA_TIN_ALTITUDE_M,
          ),
          duration: 1.2,
        });
      }
    },
    [],
  );

  const handleSubmit = useCallback(async () => {
    const drawer = drawerRef.current;
    if (!drawer || drawer.pointCount < 2 || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await checkFlightPlan(drawer.toRouteGeoJson(), {
        max_altitude_ft: altitudeFt,
      });
      drawer.showVerdict(res);
      setVerdict(res);
      setVerdictCardOpen(true);
      setDrawActive(false);
    } catch {
      setSubmitError("Check failed — is the backend running on :43124?");
    } finally {
      setSubmitting(false);
    }
  }, [altitudeFt, submitting]);

  const handleUndo = useCallback(() => drawerRef.current?.undo(), []);

  const handleClear = useCallback(() => {
    drawerRef.current?.clear();
    setVerdict(null);
    setVerdictCardOpen(false);
    setSubmitError(null);
  }, []);

  return (
    <div className="absolute inset-0">
      <div ref={containerRef} className="absolute inset-0" />
      {ready && (
        <MapToolbar
          rfzVisible={rfzVisible}
          onRfzVisibleChange={handleRfzToggle}
          rfzError={rfzError}
          drawActive={drawActive}
          onDrawActiveChange={setDrawActive}
          pointCount={pointCount}
          altitudeFt={altitudeFt}
          onAltitudeFtChange={setAltitudeFt}
          onUndo={handleUndo}
          onClear={handleClear}
          onSubmit={handleSubmit}
          submitting={submitting}
          submitError={submitError}
          verdict={verdict?.verdict ?? null}
          onReopenVerdict={() => setVerdictCardOpen(true)}
        />
      )}
      {ready && verdict && verdictCardOpen && (
        <VerdictCard result={verdict} onClose={() => setVerdictCardOpen(false)} />
      )}
    </div>
  );
}
