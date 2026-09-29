// Copies Cesium's runtime static assets (workers, widgets, third-party libs)
// into public/ so they are served at CESIUM_BASE_URL (/cesium/). Runs on
// postinstall; public/cesium is git-ignored.
import { cpSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "cesium", "Build", "Cesium");
const dest = join(root, "public", "cesium");

if (!existsSync(src)) {
  console.warn("[cesium] package not installed yet — skipping asset copy");
  process.exit(0);
}

for (const dir of ["Assets", "ThirdParty", "Widgets", "Workers"]) {
  cpSync(join(src, dir), join(dest, dir), { recursive: true });
}
console.log("[cesium] static assets copied to public/cesium");
