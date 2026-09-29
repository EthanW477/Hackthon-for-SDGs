# Data Sources & Licences

Every dataset under `data/` must be recorded here before use (project-plan
§7.1 step 0.3). Dataset files themselves stay out of git — see `data/.gitignore`
and `scripts/download_data.sh`.

| Dataset | Source | Format | Licence | Local path | Notes |
|---|---|---|---|---|---|
| HK 3D building models | Lands Department 3D Digital Map | Cesium 3D Tiles | TODO: confirm terms | `tiles/` | Or configure a remote tiles URL |
| Restricted Flying Zones (286 RFZ) | eSUA map interface snapshot | GeoJSON | TODO: confirm — **mark as unofficial snapshot in demo** | `rfz/` | Non-official provenance must be disclosed |
| Population density 100 m grid | WorldPop | GeoTIFF | CC BY 4.0 | `population/` | |
| Emergency facilities POI (hospitals / fire / police) | iGeoCom / data.gov.hk | GeoJSON | TODO: confirm terms | `poi/` | |
| CAD small-UAS regulations (20 docs) | CAD website (AC-001~017 + 3 UCA docs) | PDF | TODO: confirm terms | `regulations/` | RAG corpus |

Known gap (project-plan §4.2): no public historical drone flight/incident data
for Hong Kong — incident-investigation features are out of scope.
