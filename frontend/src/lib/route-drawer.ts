/**
 * RouteDrawer — Cesium-side controller for the route drawing tool (plan §4.5,
 * step 2.3). Owns all globe interaction and entities for:
 *   - click-to-add waypoints with a live preview polyline (rubber-bands to cursor)
 *   - undo / clear
 *   - verdict annotation after POST /api/v1/flight-plans/check:
 *     rejected segments in red, suggested alternative routes in green
 *
 * React never touches Cesium directly: it drives this controller and receives
 * point-count snapshots through the onChange listener.
 */
import type { CustomDataSource, Entity, Viewer } from "cesium";
import type { CesiumModule } from "./rfz";
import type { FlightPlanCheckResponse } from "./api";

export interface LonLat {
  lon: number;
  lat: number;
}

const FT_TO_M = 0.3048;

const COLOR_ROUTE = "#22d3ee"; // cyan while drawing
const COLOR_APPROVED = "#10b981"; // emerald
const COLOR_REJECTED = "#ef4444"; // red
const COLOR_ROUTE_DIM = "#e2e8f0"; // dimmed base when only some segments fail
const COLOR_SUGGESTION = "#22c55e"; // green alternative
/** Visual lift for suggestion lines so they never z-fight the drawn route. */
const SUGGESTION_LIFT_M = 10;

export class RouteDrawer {
  private readonly viewer: Viewer;
  private readonly Cesium: CesiumModule;
  private readonly drawDs: CustomDataSource;
  private readonly annotationDs: CustomDataSource;
  private readonly handler: InstanceType<CesiumModule["ScreenSpaceEventHandler"]>;
  private readonly onChange: (pointCount: number) => void;

  private points: LonLat[] = [];
  private pointEntities: Entity[] = [];
  private hover: LonLat | null = null;
  private altitudeM = 250 * FT_TO_M;
  private active = false;

  constructor(
    Cesium: CesiumModule,
    viewer: Viewer,
    onChange: (pointCount: number) => void,
  ) {
    this.Cesium = Cesium;
    this.viewer = viewer;
    this.onChange = onChange;
    this.drawDs = new Cesium.CustomDataSource("route-draw");
    this.annotationDs = new Cesium.CustomDataSource("route-verdict");
    viewer.dataSources.add(this.drawDs);
    viewer.dataSources.add(this.annotationDs);

    // The route line is one entity whose positions recompute on every frame:
    // confirmed waypoints plus the cursor position while drawing (live preview).
    this.drawDs.entities.add({
      polyline: {
        positions: new Cesium.CallbackProperty(() => this.linePositions(), false),
        width: 4,
        material: Cesium.Color.fromCssColorString(COLOR_ROUTE),
        arcType: Cesium.ArcType.NONE,
      },
    });

    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    this.handler.setInputAction(
      (e: { position: InstanceType<CesiumModule["Cartesian2"]> }) => this.onClick(e.position),
      Cesium.ScreenSpaceEventType.LEFT_CLICK,
    );
    this.handler.setInputAction(
      (e: { endPosition: InstanceType<CesiumModule["Cartesian2"]> }) =>
        this.onMouseMove(e.endPosition),
      Cesium.ScreenSpaceEventType.MOUSE_MOVE,
    );
    // Don't let double-click grab the camera / track an entity mid-drawing.
    viewer.screenSpaceEventHandler.removeInputAction(
      Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK,
    );
  }

  get pointCount(): number {
    return this.points.length;
  }

  setActive(active: boolean): void {
    this.active = active;
    this.viewer.canvas.style.cursor = active ? "crosshair" : "";
    if (active) {
      // A new drawing session supersedes the previous verdict display.
      this.clearAnnotations();
    } else {
      this.hover = null;
    }
  }

  setAltitudeFt(ft: number): void {
    if (Number.isFinite(ft) && ft > 0) this.altitudeM = ft * FT_TO_M;
  }

  undo(): void {
    const entity = this.pointEntities.pop();
    if (entity) this.drawDs.entities.remove(entity);
    this.points.pop();
    this.notify();
  }

  clear(): void {
    this.points = [];
    this.pointEntities = [];
    this.hover = null;
    // Keep entity index 0: the route line itself.
    this.drawDs.entities.suspendEvents();
    for (let i = this.drawDs.entities.values.length - 1; i >= 1; i--) {
      this.drawDs.entities.remove(this.drawDs.entities.values[i]);
    }
    this.drawDs.entities.resumeEvents();
    this.clearAnnotations();
    this.notify();
  }

  /** GeoJSON LineString for the API contract: [[lon, lat, alt_m], ...]. */
  toRouteGeoJson(): Record<string, unknown> {
    return {
      type: "LineString",
      coordinates: this.points.map((p) => [
        Number(p.lon.toFixed(6)),
        Number(p.lat.toFixed(6)),
        Math.round(this.altitudeM),
      ]),
    };
  }

  /** Render the /flight-plans/check verdict on the globe. */
  showVerdict(res: FlightPlanCheckResponse): void {
    this.clearAnnotations();
    const routeEntity = this.drawDs.entities.values[0];
    const routeLine = routeEntity?.polyline;
    if (!routeLine) return;

    if (res.verdict === "approved") {
      routeLine.material = new this.Cesium.ColorMaterialProperty(
        this.Cesium.Color.fromCssColorString(COLOR_APPROVED),
      );
    } else {
      const failedSegments = new Set(
        res.violations
          .map((v) => v.segment_index)
          .filter((i): i is number => typeof i === "number" && i >= 0),
      );
      if (failedSegments.size === 0) {
        // Contract allows violations without a segment index — reject whole route.
        routeLine.material = new this.Cesium.ColorMaterialProperty(
          this.Cesium.Color.fromCssColorString(COLOR_REJECTED),
        );
      } else {
        routeLine.material = new this.Cesium.ColorMaterialProperty(
          this.Cesium.Color.fromCssColorString(COLOR_ROUTE_DIM).withAlpha(0.7),
        );
        for (const i of failedSegments) {
          const a = this.points[i];
          const b = this.points[i + 1];
          if (!a || !b) continue;
          this.annotationDs.entities.add({
            polyline: {
              positions: [this.toCartesian(a), this.toCartesian(b)],
              width: 8,
              material: this.Cesium.Color.fromCssColorString(COLOR_REJECTED),
              arcType: this.Cesium.ArcType.NONE,
            },
          });
        }
      }
    }

    // Suggested alternatives (counterfactuals) render in green when the
    // response carries a patched route geometry.
    for (const suggestion of res.suggestions) {
      const coords = this.lineStringCoords(suggestion.patched_route_geojson);
      if (!coords || coords.length < 2) continue;
      this.annotationDs.entities.add({
        polyline: {
          positions: coords.map(([lon, lat, alt]) =>
            this.Cesium.Cartesian3.fromDegrees(
              lon,
              lat,
              (alt ?? this.altitudeM) + SUGGESTION_LIFT_M,
            ),
          ),
          width: 5,
          material: new this.Cesium.PolylineDashMaterialProperty({
            color: this.Cesium.Color.fromCssColorString(COLOR_SUGGESTION),
          }),
          arcType: this.Cesium.ArcType.NONE,
        },
      });
    }
  }

  clearAnnotations(): void {
    this.annotationDs.entities.removeAll();
    const routeLine = this.drawDs.entities.values[0]?.polyline;
    if (routeLine) {
      routeLine.material = new this.Cesium.ColorMaterialProperty(
        this.Cesium.Color.fromCssColorString(COLOR_ROUTE),
      );
    }
  }

  destroy(): void {
    this.handler.destroy();
    this.viewer.dataSources.remove(this.drawDs, true);
    this.viewer.dataSources.remove(this.annotationDs, true);
  }

  // ---------- internals ----------

  private notify(): void {
    this.onChange(this.points.length);
  }

  private toCartesian(p: LonLat): InstanceType<CesiumModule["Cartesian3"]> {
    return this.Cesium.Cartesian3.fromDegrees(p.lon, p.lat, this.altitudeM);
  }

  private linePositions(): InstanceType<CesiumModule["Cartesian3"]>[] {
    const pts = this.active && this.hover ? [...this.points, this.hover] : this.points;
    if (pts.length < 2) return [];
    return pts.map((p) => this.toCartesian(p));
  }

  private pickLonLat(
    screenPos: InstanceType<CesiumModule["Cartesian2"]>,
  ): LonLat | null {
    const cartesian = this.viewer.camera.pickEllipsoid(
      screenPos,
      this.viewer.scene.globe.ellipsoid,
    );
    if (!cartesian) return null;
    const carto = this.Cesium.Cartographic.fromCartesian(cartesian);
    return {
      lon: this.Cesium.Math.toDegrees(carto.longitude),
      lat: this.Cesium.Math.toDegrees(carto.latitude),
    };
  }

  private onClick(screenPos: InstanceType<CesiumModule["Cartesian2"]>): void {
    if (!this.active) return;
    const p = this.pickLonLat(screenPos);
    if (!p) return;
    this.points.push(p);
    this.pointEntities.push(
      this.drawDs.entities.add({
        position: this.toCartesian(p),
        point: {
          pixelSize: 9,
          color: this.Cesium.Color.fromCssColorString(COLOR_ROUTE),
          outlineColor: this.Cesium.Color.WHITE,
          outlineWidth: 2,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      }),
    );
    this.notify();
  }

  private onMouseMove(screenPos: InstanceType<CesiumModule["Cartesian2"]>): void {
    if (!this.active || this.points.length === 0) return;
    this.hover = this.pickLonLat(screenPos);
  }

  private lineStringCoords(geojson: unknown): [number, number, number?][] | null {
    if (!geojson || typeof geojson !== "object") return null;
    const g = geojson as { type?: string; coordinates?: unknown };
    if (g.type === "LineString" && Array.isArray(g.coordinates)) {
      return g.coordinates as [number, number, number?][];
    }
    // Accept a bare Feature too — cheap tolerance for contract drift.
    if (g.type === "Feature") {
      return this.lineStringCoords((g as { geometry?: unknown }).geometry);
    }
    return null;
  }
}
