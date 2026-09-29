# Data Sources & Licences

Every dataset under `data/` must be recorded here before use (project-plan
§7.1 step 0.3). Dataset files themselves stay out of git — see `data/.gitignore`
and `scripts/download_data.sh`, which re-downloads everything below.

All retrieval dates: **2026-09-29**. Verified copies are also cached in the
project agent store under `internal/datasets/<category>/`.

| Dataset | Source (exact URL) | Format | Licence / terms | Local path | Size | Notes / caveats |
|---|---|---|---|---|---|---|
| Restricted Flying Zones (290 polygons, 252 named zones) | `POST https://esua.cad.gov.hk/web/droneMap/getData` (CAD eSUA drone map internal endpoint) | GeoJSON (WGS84) | **No open licence** — eSUA page states data is "for general reference only"; endpoint is undocumented | `rfz/hk_rfz_esua_snapshot.geojson` (+ `rfz/esua_rfz_raw.json`) | ~3.3 MB | **Unofficial snapshot — disclose provenance in demo.** Cache once, do not scrape. Authoritative list is Gazette G.N. 8002 (names only, no coordinates): https://www.cad.gov.hk/documents/G.N.8002_C.pdf |
| CAD small-UAS advisory circulars AC-001–AC-017 (17 PDFs) | `https://www.cad.gov.hk/documents/AC-0XX[_C].pdf` (see `scripts/download_data.sh` for the full URL list) | PDF | CAD website content; government copyright, used here as a RAG reference corpus with attribution | `regulations/` | ~11 MB total | AC-014 (Cat C ops, 2026-07-31), AC-015 (façade cleaning), AC-016 (docking stations), AC-017 (Sandbox X cross-boundary) are the newest. Chinese versions where available (`_C` suffix) |
| UCA trial documents (3 PDFs) | https://www.cad.gov.hk/documents/uca_trials_guidance.pdf · https://www.cad.gov.hk/documents/AC-UCA001.pdf · https://www.cad.gov.hk/documents/Template_of_Operations_Manual_ZH.pdf | PDF | Same as above | `regulations/` | incl. above | AIC 20/25 guidance, insurance requirements, ops-manual template for unconventional aircraft trials (Air Navigation (HK) Order 1995 Part IXA) |
| Population density 100 m grid (2026) | https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2026/HKG/v1/100m/constrained/hkg_pop_2026_CN_100m_R2025A_v1.tif | GeoTIFF (EPSG:4326, 728×491, ~100 m, float32 persons/pixel) | **CC BY 4.0** (attribute WorldPop, University of Southampton) | `population/hkg_pop_2026_CN_100m_R2025A_v1.tif` | 371 KB | WorldPop R2025A constrained estimates; verified total ≈ 7.39 M. Hub page: https://hub.worldpop.org/geodata/summary?id=73760 |
| Emergency facilities POI (432 features: 95 fire stations, 92 police stations, 60 hospitals, 45 ambulance depots, 140 helipads) | https://open.hkmapservice.gov.hk/OpenData/directDownload?productName=iGeoCom&sheetName=iGeoCom&productFormat=GEOJSON (LandsD iGeoCom via data.gov.hk dataset `hk-landsd-openmap-development-hkms-digital-geocom`) | GeoJSON (WGS84 points); full set 37,379 POIs also kept | data.gov.hk Terms & Conditions of Use (free for commercial/non-commercial use with attribution to LandsD) | `poi/emergency_facilities_hk.geojson` (subset), `poi/iGeoCOM_POI.geojson` (full) | 185 KB / 50 MB | Subset extracted by iGeoCom CLASS/TYPE codes (GOV/FSN, GOV/PSN, GOV/ABL, HNC/HOS, TRS/HLP). **SSL caveat:** `open.hkmapservice.gov.hk` chains to Hongkong Post e-Cert CA, missing from some CA bundles — script falls back to `curl -k` with a warning |
| Real-time weather (HKO open data API) | `https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType={flw,fnd,rhrread,warnsum,warningInfo,swt}&lang={en,tc,sc}`; visibility: `.../opendata/opendata.php?dataType=LTMV&rformat=json`; rain: `.../opendata/hourlyRainfall.php` | JSON (live API, no bulk download) | HKO open data — free with attribution "Hong Kong Observatory" | `weather/` (sample responses only) | samples ~18 KB | **No API key required** — all endpoints verified HTTP 200 on 2026-09-29. Docs: https://www.weather.gov.hk/tc/weatherAPI/doc/files/HKO_Open_Data_API_Documentation_sc.pdf. `rhrread` = current district weather (temp/humidity/rain/wind, 27 stations); `warnsum`/`warningInfo` = active warnings; `LTMV` = 10-min mean visibility |
| HK 3D building tiles (LandsD 3D Visualisation Map, territory-wide) | Viewer: https://3d.map.gov.hk · Tile API: `https://data.map.gov.hk/api/3d-data/3dtiles/...` · CSDI geoportal dataset `landsd_rcd_1671677054006_62261` · data.gov.hk dataset `hk-landsd-openmap-3d-visualisation-map-tile-based-models` | Cesium 3D Tiles | CSDI / data.gov.hk terms (free with attribution) | `tiles/` (empty — see below) | — | **Manual step:** tile API returns HTTP 401 without a subscription key. Register a free CSDI account at https://portal.csdi.gov.hk, then request a Map API key, and pass it as `?key=...`. Configure the resulting tileset URL in the frontend instead of committing tiles |
| 3D photo-realistic model fallback (PlanD, HK Island + Kowloon only, 2017/18 imagery) | `https://pdmap.pland.gov.hk/plandapi/Tiles?e=<E>&n=<N>&fileType=CESIUM` (HK1980 grid coords) → JSON with direct zip URLs | Cesium 3D Tiles (zip per tile) | data.gov.hk terms (dataset `hk-pland-pland1-3d-photo-realistic-model`) | `tiles/` (optional sample) | ~334 MB per tile | **No key required** — verified 2026-09-29. `scripts/download_data.sh --pland-sample` fetches one sample tile (Sheung Wan–Pok Fu Lam) |

## HKO API quick reference (verified 2026-09-29)

```bash
# Current district weather (temperature, humidity, rainfall, wind — 27 stations)
curl 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en'
# Active weather warnings summary
curl 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=en'
# Detailed warning info (thunderstorm, strong wind, ...)
curl 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warningInfo&lang=en'
# Latest 10-minute mean visibility (4 stations)
curl 'https://data.weather.gov.hk/weatherAPI/opendata/opendata.php?dataType=LTMV&lang=en&rformat=json'
# Hourly rainfall by district (15-min updates)
curl 'https://data.weather.gov.hk/weatherAPI/opendata/hourlyRainfall.php?lang=en'
```

Response shapes (top level): `rhrread` → `{rainfall:{data:[{place,value,unit}],startTime,endTime}, temperature:{data:[...27 items]}, humidity, uvindex, icon, updateTime, warningMessage}`;
`warnsum` → `{<WCODE>: {name, code, actionCode, issueTime, updateTime}}` (empty object when no warnings);
`warningInfo` → `{details: [{contents: [...], warningStatementCode, subtype, updateTime}]}`;
`LTMV` → `{fields: [...3], data: [[DateTime, station, visibility_km]...]}`;
`hourlyRainfall` → `{obsTime, hourlyRainfall: [{automaticWeatherStation, automaticWeatherStationID, value, unit}]}` (36 stations).

## Known gaps (project-plan §4.2)

- No public historical drone flight/incident data for Hong Kong — incident features
  must be synthesised by the rules engine.
- 《无人机交通管理系统演示指南》(UTM demonstration guidelines) full text is not
  public; the rules layer encodes Cap. 448G + SRD + AC-014/015/016/017 instead.
- Bamboo Bay (Penny's Bay) flight prohibition under Cap. 448E is **not** in the
  eSUA map; crewed-aviation prohibited/restricted areas (VHP8, VHR12, VHR13,
  VHD…) are in eAIP ENR 5.1 at https://www.ais.gov.hk/ if needed later.
