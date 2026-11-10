# SafeJourney — project context

## Purpose

Build an educational journey safety monitoring application. Communicate in Vietnamese and explain changes at a beginner-friendly level. Read README.md and docs/03-lo-trinh-phat-trien.md for current state. docs/01-phan-tich-giai-phap.md distinguishes implemented behavior from the broader target architecture.

## Layout

- backend/app: FastAPI, database access, sessions/RBAC, telemetry detector and LangGraph planner.
- backend/app/api: capability routers; main.py composes the app. schemas.py defines request/response contracts; telemetry_policy.py contains pure timing rules.
- backend/app/operations: bounded advisory LangGraph team, deterministic fare/EV/charging tools, H3, OSRM and OR-Tools. Read docs/09 before extending; calculations never authorize actions.
- backend/migrations: ordered SQL migrations with checksums; apply with python -m app.db. Never modify an already-applied migration; add the next numbered file.
- backend/tests: unit and isolated integration tests.
- frontend/src: React dashboard, optional Mapbox; frontend/tests covers pure frontend logic.
- simulator.py: synthetic GPS/SOS producer; keep at repository root. tests/test_simulator.py covers it.
- docs/02-huong-dan-cai-dat-va-lap-trinh.md: current beginner tutorial linked directly to actual source, without duplicated source snapshots.
- compose.yaml: local PostgreSQL/PostGIS and Redis. Dockerfile and fly.toml.example at root.
- load_tests: isolated local PostgreSQL/Redis (25432/26379), API 18000, open-loop workload. Read docs/06 before running.
- research_benchmarks: offline real TLC zone-hour evaluation; read docs/10. Raw Parquet is ignored; preserve report provenance. TLC has no GPS trajectory or SOS labels.

## Development

- Python 3.12; Node 22.12+ (Node 24 LTS recommended).
- Local Python is managed by Anaconda/Conda. Create the named environment from the repository root with conda env create -f environment.yml; activate safejourney in every Python terminal. Do not install project packages into base.
- Windows: use python from the active safejourney environment and npm.cmd. For non-interactive commands use conda run --no-capture-output -n safejourney python. Do not hardcode an Anaconda install path or use the legacy .venv.
- environment.yml installs Python 3.12 and pip, then load_tests/requirements.txt (backend, dev tests and aiohttp) and research_benchmarks/requirements.txt (PyArrow). Application versions stay in requirements files; Docker uses backend/requirements.txt without Conda.
- Backend working directory is backend; API, Detector and Planner run separately.
- One Detector and one Planner per database: preserve singleton locks until partition/lease architecture is implemented.
- Rule check from backend after activation: python -m pytest tests/test_rules.py -q.
- Root checks after activation: python -m pytest tests load_tests/tests research_benchmarks/tests -q.
- Frontend: npm.cmd ci, npm.cmd test, npm.cmd run build.
- Read tutorial section 12.2 before integration tests. Require RUN_DEMO_TESTS=1, local safejourney_test/safejourney_loadtest and synthetic data.
- Prefer safejourney_test + Redis DB1 for integration, safejourney_loadtest + Redis DB0 for load tests. Stop Detector/Planner before integration; never run integration during load.
- Preserve failing load reports and thresholds. Do not edit measured source during a load run; schema 3 reports its fingerprint.
- Secrets stay in ignored .env files. Frontend VITE configuration is public.
- Never delete database volumes as routine troubleshooting.

## Product constraints

- All actions are simulated. Emergency external actions require backend human approval; LLM output is never authorization.
- Routine playbooks run automatically under backend policy; confirmation means an authenticated reply from the actual recipient. Only emergency escalation uses HITL. Preserve the two-contact limit, deadlines, proposal revision, and scoped contact replies.
- Read docs/08-quy-trinh-operator-va-phan-cong.md for autonomous SMS/call, recipient confirmation, operator ownership and migration behavior. Never interpret a simulated send as a recipient reply or auto-close an emergency.
- Preserve scoped access to trips, location, SOS and incident history.
- Rules detect without waiting for LLM. Preserve idempotency for telemetry, SOS and approvals.
- Report verification accurately: unit mocks, real local DB/API, browser, deployed environment and planned work are distinct.
- HTTP 200 from /api/health verifies DB reachability, not full pipeline health.

## Documentation

Use UTF-8 and descriptive numbered documents in docs. Maintain a single current set: no old source appendix or parallel version guides. Link explanations to actual repository files and update docs alongside behavior changes.

docs/05 describes module boundaries and current optimizations; docs/06 explains the load harness; docs/07 contains the current measured verification and limitations. Keep older raw benchmark JSON as evidence, but do not present it as current performance. Prefer small verifiable changes over reorganizing working paths.

