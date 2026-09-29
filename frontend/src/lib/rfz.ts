/**
 * RFZ (Restricted Flying Zone) map layer — plan step 1.2: red, semi-transparent,
 * toggleable polygons.
 *
 * Data source: a synthetic sample shipped at public/sample-rfz.geojson while the
 * real 286-zone set is being fetched into data/rfz/ by the data pipeline.
 * Swapping to the real file (or a backend endpoint) is a one-line change to
 * RFZ_SOURCE_URL below — the loader only needs a GeoJSON FeatureCollection of
 * Polygon/MultiPolygon features.
 */
import type { CustomDataSource, Viewer } from "cesium";

export type CesiumModule = typeof import("cesium");

// --- the one-line swap -------------------------------------------------------
export const RFZ_SOURCE_URL = "/sample-rfz.geojson";
// Real data, once available — pick one:
// export const RFZ_SOURCE_URL = "/rfz/hong-kong-rfz.geojson"; // static export of data/rfz
// export const RFZ_SOURCE_URL = `${process.env.NEXT_PUBLIC_API_URL}/api/v1/rfz`; // backend endpoint
// -----------------------------------------------------------------------------

const RFZ_FILL = "#ff3b30";
const RFZ_FILL_ALPHA = 0.28;
const RFZ_BORDER = "#ff2d20";

type Ring = [number, number][];

function extractRings(geometry: unknown): Ring[] {
  if (!geometry || typeof geometry !== "object") return [];
  const g = geometry as { type?: string; coordinates?: unknown };
  if (g.type === "Polygon" && Array.isArray(g.coordinates)) {
    // outer ring only — RFZ zones in the source data have no holes
    return [g.coordinates[0] as Ring].filter((r) => Array.isArray(r) && r.length >= 4);
  }
  if (g.type === "MultiPolygon" && Array.isArray(g.coordinates)) {
    return (g.coordinates as Ring[][])
      .map((poly) => poly[0])
      .filter((r) => Array.isArray(r) && r.length >= 4);
  }
  return [];
}

/** Fetch the RFZ GeoJSON and add it to the viewer as a styled data source. */
export async function loadRfzLayer(
  Cesium: CesiumModule,
  viewer: Viewer,
  url: string = RFZ_SOURCE_URL,
): Promise<CustomDataSource> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`RFZ fetch failed: ${res.status} ${res.statusText}`);
  const geojson = (await res.json()) as { features?: unknown[] };

  const fill = Cesium.Color.fromCssColorString(RFZ_FILL).withAlpha(RFZ_FILL_ALPHA);
  const border = Cesium.Color.fromCssColorString(RFZ_BORDER);

  const ds = new Cesium.CustomDataSource("rfz");
  for (const feature of geojson.features ?? []) {
    const f = feature as {
      properties?: Record<string, unknown> | null;
      geometry?: unknown;
    };
    const props = f.properties ?? {};
    const name = typeof props.name === "string" ? props.name : "Restricted Flying Zone";
    for (const ring of extractRings(f.geometry)) {
      const positions = Cesium.Cartesian3.fromDegreesArray(ring.flat());
      ds.entities.add({
        name,
        description: [props.id, props.category, props.remarks]
          .filter((v) => typeof v === "string" && v.length > 0)
          .join("<br/>"),
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(positions),
          material: fill,
          // No height/extrudedHeight: Cesium renders this as a ground
          // primitive automatically (clampToGround was removed from
          // PolygonGraphics). Ground primitives don't support outlines, so
          // the border is a separate clamped polyline below.
          classificationType: Cesium.ClassificationType.BOTH,
        },
      });
      ds.entities.add({
        name: `${name} (boundary)`,
        polyline: {
          positions,
          width: 2,
          material: border,
          clampToGround: true,
        },
      });
    }
  }
  await viewer.dataSources.add(ds);
  return ds;
}
