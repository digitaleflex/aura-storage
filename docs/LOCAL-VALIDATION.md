# Local validation (non-destructive)

What to run before pushing, and what each result does and does not prove. None of
it touches the pilot: no deployment, no Docker/host change, no SSH.

> Passing these checks is **not** acceptance on the pilot. The stack still has to
> pass the gates listed in the [README](../README.md).

## 1. API (pytest)

```bash
python3 -m venv .venv && .venv/bin/pip install -r api/requirements-dev.txt
AURA_API_ADMIN_PASSWORD=ci AURA_S3_ACCESS_KEY=ci-1234567890 \
AURA_S3_SECRET_KEY=ci-12345678901234567890 AURA_S3_ENDPOINT=https://127.0.0.1:9 \
AURA_API_DB=:memory: AURA_COOKIE_SECURE=0 .venv/bin/python -m pytest tests/ -q -rs
```

* Use `-rs`: it lists **skipped** tests. A skipped test is not a pass. Two are
  expected without extra setup: the live S3 test (`AURA_LIVE_S3=1`, needs a real
  SeaweedFS) and the PostgreSQL parity suite.
* `tests/test_openapi_contract.py` validates `docs/openapi.yaml` with
  `openapi-spec-validator`. It is **skipped when the package is missing**, and CI
  has it (it comes with `api/requirements-dev.txt`). A YAML mistake (for example an
  unquoted description containing a comma) therefore only fails in CI if you did
  not install the dev requirements. Install them.
* Add a route → document it in `docs/openapi.yaml` with a summary, a tag declared
  in the file and a 2xx response, or the contract tests fail.

## 2. API on PostgreSQL

The production catalogue is PostgreSQL; run the same suite against a disposable
instance:

```bash
AURA_API_DSN="postgresql://USER@/DB?host=/path/to/socket&port=PORT" \
  .venv/bin/python -m pytest tests/ -q -rs
AURA_TEST_PG_DSN="postgresql://..." .venv/bin/python -m pytest tests/test_pg_parity.py -q
```

SQL written in tests must work on both backends (`?` vs `%s`): see the `_sql()`
helpers in `tests/test_scrubber.py` and `tests/test_async_verify.py`.

## 3. Web

```bash
cd web
npm ci                # the lockfile must match package.json (CI runs npm ci)
npx tsc --noEmit -p .
npm run build         # tsc + vite build, what web.yml runs
```

Playwright (the CI does **not** run it, so run it yourself):

```bash
# terminal 1 — API with throwaway secrets, from the repo root
AURA_API_ADMIN_PASSWORD=local-smoke-test-password AURA_S3_ACCESS_KEY=ci-1234567890 \
AURA_S3_SECRET_KEY=ci-12345678901234567890 AURA_S3_ENDPOINT=https://127.0.0.1:9 \
AURA_API_DB=:memory: AURA_COOKIE_SECURE=0 .venv/bin/python -m uvicorn api.main:app --port 8081
# terminal 2
cd web && npm run dev
# terminal 3
cd web && npx playwright test --ignore-snapshots
```

* `--ignore-snapshots`: the baselines in `e2e/visual-regression.spec.ts-snapshots`
  come from another machine's rendering and fail on a different one.
* If the browser is not downloaded in your environment, point a local config at an
  installed Chromium (`launchOptions.executablePath`) instead of running
  `playwright install`.
* Run the whole suite more than once before trusting a new test: two tests of this
  project were found to fail one run in four.

## 4. Shell and configuration

```bash
bash -n scripts/*.sh tests/*.sh
bash tests/test-s3-smoke-validation.sh && bash tests/test-backup-scripts.sh
python3 -m json.tool config/seaweedfs/s3.json.example > /dev/null
cp .env.example .env && bash scripts/generate-config.sh && docker compose config --quiet
git check-ignore .env config/seaweedfs/s3.json
```

* `tests/test-landing-routing.sh` needs `envsubst` (package `gettext`); without it
  it reports failures that are not repository defects.
* `.env` and `config/seaweedfs/s3.json` are git-ignored: never commit them.
* `tests/sse-s3-smoke-test.sh` and `tests/s3-smoke-test.sh` need a real endpoint;
  do not run them against production without explicit approval.

## 5. Report

For each change, state: files changed, tests run **with their real result**, tests
not run and why, remaining risks. "Tests pass" with skipped tests is not "tests
pass".
