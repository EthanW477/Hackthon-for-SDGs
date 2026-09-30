#!/usr/bin/env bash
# download_data.sh — fetch all Phase 1 datasets into data/ (project-plan §7.1 step 0.3).
# Provenance and licences: data/SOURCES.md. All sources verified 2026-09-29.
#
# Usage:
#   ./scripts/download_data.sh                 # download everything (except 3D tiles)
#   ./scripts/download_data.sh --pland-sample  # also fetch one PlanD Cesium sample tile (~334 MB)
#
# Requires: bash, curl, python3, unzip.
# Note: LandsD territory-wide 3D tiles need a free CSDI API key — see the
# "HK 3D building tiles" row in data/SOURCES.md; this script only prints instructions.

set -euo pipefail
cd "$(dirname "$0")/.."

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
DL=curl
dl() { # dl <url> <outfile>  — retry + govHK cert fallback
  local url="$1" out="$2"
  "$DL" -sS -L --retry 3 --max-time 600 -A "$UA" -o "$out" "$url" 2>/dev/null || {
    echo "  ! TLS verify failed for $url — retrying with -k (Hongkong Post e-Cert CA missing from bundle)" >&2
    "$DL" -sS -k -L --retry 3 --max-time 600 -A "$UA" -o "$out" "$url"
  }
}

echo '==> 1/5 Restricted Flying Zones (eSUA snapshot)'
mkdir -p data/rfz
curl -sS --retry 3 --max-time 120 -A "$UA" -X POST \
  'https://esua.cad.gov.hk/web/droneMap/getData' -o data/rfz/esua_rfz_raw.json
python3 - <<'PY'
import json
raw = json.load(open('data/rfz/esua_rfz_raw.json'))
data = raw['data']
feats = []
for s in data['rfzFeatures']:
    feats.extend(json.loads(s).get('features', []))
keep = ['name', 'effectiveDateTime', 'description', 'description2', 'link']
clean = [{'type': 'Feature', 'geometry': f['geometry'],
          'properties': {k: f['properties'][k] for k in keep
                         if f['properties'].get(k) not in (None, '')}}
         for f in feats]
out = {'type': 'FeatureCollection',
       'metadata': {'source': 'CAD eSUA drone map (undocumented getData endpoint)',
                    'retrieved_by': 'scripts/download_data.sh',
                    'note': 'UNOFFICIAL snapshot of Cap. 448G s.19 RFZs — demo use only; '
                            'authoritative list is Gazette G.N. 8002 (names only)'},
       'features': clean}
json.dump(out, open('data/rfz/hk_rfz_esua_snapshot.geojson', 'w'), ensure_ascii=False)
print(f'  rfz: {len(clean)} polygon features -> data/rfz/hk_rfz_esua_snapshot.geojson')
PY

echo '==> 2/5 CAD regulation PDFs (AC-001..017 + 3 UCA docs)'
mkdir -p data/regulations
while read -r name url; do
  [ -z "$name" ] && continue
  dl "$url" "data/regulations/$name"
  head -c 5 "data/regulations/$name" | grep -q '%PDF-' \
    && echo "  ok $name" || { echo "  FAILED $name (not a PDF)" >&2; rm -f "data/regulations/$name"; }
done <<'EOF'
AC-001_C.pdf https://www.cad.gov.hk/documents/AC-001_C.pdf
AC-002_C.pdf https://www.cad.gov.hk/documents/AC-002_C.pdf
AC-003_C.pdf https://www.cad.gov.hk/documents/AC-003_C.pdf
AC-004_C.pdf https://www.cad.gov.hk/documents/AC-004_C.pdf
AC-005_C.pdf https://www.cad.gov.hk/documents/AC-005_C.pdf
AC-006_C.pdf https://www.cad.gov.hk/documents/AC-006_C.pdf
AC-007_C.pdf https://www.cad.gov.hk/documents/AC-007_C.pdf
AC-008_C.pdf https://www.cad.gov.hk/documents/AC-008_C.pdf
AC-009_C.pdf https://www.cad.gov.hk/documents/AC-009_C.pdf
AC-010.pdf https://www.cad.gov.hk/documents/AC-010.pdf
AC-011_C.pdf https://www.cad.gov.hk/documents/AC-011_C.pdf
AC-012.pdf https://www.cad.gov.hk/documents/AC-012.pdf
AC-013_C.pdf https://www.cad.gov.hk/documents/AC-013_C.pdf
AC-014_C.pdf https://www.cad.gov.hk/documents/AC-014_C.pdf
AC-015_C.pdf https://www.cad.gov.hk/documents/AC-015_C.pdf
AC-016_C.pdf https://www.cad.gov.hk/documents/AC-016_C.pdf
AC-017.pdf https://www.cad.gov.hk/documents/AC-017.pdf
UCA_AIC-20-25_uca_trials_guidance.pdf https://www.cad.gov.hk/documents/uca_trials_guidance.pdf
UCA_AC-UCA001_insurance.pdf https://www.cad.gov.hk/documents/AC-UCA001.pdf
UCA_ops_manual_template_ZH.pdf https://www.cad.gov.hk/documents/Template_of_Operations_Manual_ZH.pdf
EOF

echo '==> 3/5 WorldPop 100 m population grid (CC BY 4.0)'
mkdir -p data/population
dl 'https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/HKG/v1/100m/constrained/hkg_pop_2026_CN_100m_R2025A_v1.tif' \
   data/population/hkg_pop_2026_CN_100m_R2025A_v1.tif
echo '  ok population/hkg_pop_2026_CN_100m_R2025A_v1.tif'

echo '==> 4/5 Emergency facility POIs (LandsD iGeoCom)'
mkdir -p data/poi
dl 'https://open.hkmapservice.gov.hk/OpenData/directDownload?productName=iGeoCom&sheetName=iGeoCom&productFormat=GEOJSON' \
   data/poi/iGeoCom.zip
unzip -o -q data/poi/iGeoCom.zip -d data/poi/
python3 - <<'PY'
import json
fc = json.load(open('data/poi/iGeoCOM_POI.geojson'))
want = {('GOV', 'FSN'): 'fire_station', ('GOV', 'PSN'): 'police_station',
        ('GOV', 'ABL'): 'ambulance_depot', ('HNC', 'HOS'): 'hospital',
        ('TRS', 'HLP'): 'helipad'}
out = []
for f in fc['features']:
    p = f['properties']
    k = (p.get('CLASS'), p.get('TYPE'))
    if k in want:
        out.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {
            'facility_type': want[k], 'name_en': p.get('ENGLISHNAME'),
            'name_zh': p.get('CHINESENAME'), 'address_en': p.get('E_ADDRESS'),
            'address_zh': p.get('C_ADDRESS'), 'district_en': p.get('E_DISTRICT'),
            'tel': p.get('TEL_NO'), 'subcat': p.get('SUBCAT'),
            'source': 'iGeoCom', 'rev_date': p.get('REV_DATE')}})
res = {'type': 'FeatureCollection',
       'metadata': {'source': 'LandsD iGeoCom via data.gov.hk',
                    'licence': 'data.gov.hk Terms and Conditions of Use (attribution)'},
       'features': out}
json.dump(res, open('data/poi/emergency_facilities_hk.geojson', 'w'), ensure_ascii=False)
print(f'  poi: {len(out)} emergency facilities (of {len(fc["features"])} iGeoCom POIs)')
PY

echo '==> 5/5 HKO open-data API smoke test (live API, nothing to download)'
mkdir -p data/weather
for dt in rhrread warnsum warningInfo; do
  code=$(curl -sS --max-time 30 -o "data/weather/hko_${dt}_sample.json" -w '%{http_code}' \
    "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=${dt}&lang=en")
  echo "  hko ${dt}: HTTP ${code}"
done

cat <<'EOF'

==> HK 3D building tiles (LandsD 3D Visualisation Map) — MANUAL STEP
    Territory-wide Cesium 3D Tiles are served from
      https://data.map.gov.hk/api/3d-data/3dtiles/...?key=<SUBSCRIPTION_KEY>
    which returns HTTP 401 without a key. To get one (free):
      1. Register an account at https://portal.csdi.gov.hk
      2. Request a Map API subscription key for the 3D tiles API
      3. Put the keyed tileset URL in the frontend config (see frontend/.env.example)
    Viewer: https://3d.map.gov.hk  ·  dataset: data.gov.hk
    hk-landsd-openmap-3d-visualisation-map-tile-based-models
EOF

if [ "${1:-}" = '--pland-sample' ]; then
  echo '==> Optional: PlanD keyless 3D sample tile (HK Island/Kowloon, ~334 MB)'
  mkdir -p data/tiles
  dl 'https://pdmap.pland.gov.hk/plandapi/Tiles?e=833000&n=816000&fileType=CESIUM' data/tiles/pland_tile_index.json
  url=$(python3 -c "import json;print(json.load(open('data/tiles/pland_tile_index.json'))['gridList'][0]['file_url'])")
  echo "  downloading $url"
  dl "$url" data/tiles/pland_tile_CESIUM.zip
  unzip -o -q data/tiles/pland_tile_CESIUM.zip -d data/tiles/pland_sample/
  echo '  ok data/tiles/pland_sample/'
fi

echo 'Done. See data/SOURCES.md for provenance and licences.'
