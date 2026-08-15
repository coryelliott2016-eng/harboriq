# HarborIQ Frontend + Mobile Shell — Production Launch Audit

**Audit scope:** `/home/user/workspace/harboriq_repo/frontend` (React/Vite/TypeScript/Capacitor), read-only code audit.  
**Audited:** 2026-08-15 (EDT).  
**Overall decision:** **CONDITIONAL FAIL for a mobile-store launch; web/PWA quality gates pass.** Native store submission is not yet release-ready because iOS has only an unsigned compile check and the Android signing/account configuration cannot be validated from the repository.

## Severity key

- **P0** — critical production/security/data-loss issue or universal launch blocker
- **P1** — blocks a declared release channel or must be closed before that channel launches
- **P2** — non-blocking quality, performance, or test-signal issue

## Gate summary

| # | Gate | Status | Result |
|---|---|---|---|
| 1 | Locked dependency install | **PASS** | `npm ci` exited 0; 0 known npm audit vulnerabilities reported. |
| 2 | TypeScript | **PASS** | `npx tsc --noEmit` exited 0 with no output/errors. |
| 3 | Lint | **PASS with P2** | 0 errors, 1 warning. |
| 4 | Unit/integration tests | **PASS** | 31 test files and 128 tests passed; 0 failed. |
| 5 | Production build | **PASS with P2** | Build and generated service worker succeeded; Vite emitted a >500 kB chunk warning. |
| 6 | PWA readiness | **PASS** | Manifest and generated service worker exist; service worker registration and offline cache/queue wiring are present. |
| 7 | Mobile readiness | **FAIL (P1)** | Android/iOS shells and config exist, but store-distribution prerequisites are not complete/validated. |
| 8 | Production TODO/FIXME/mock scan | **PASS** | No production TODO/FIXME/mock or sample-data markers found; only conventional input placeholders. |
| 9 | Accessibility quick check | **PASS with P2 caveat** | `lang="en"` exists and the sole page `<img>` has an `alt`; no automated a11y lint/test tooling is installed. |

## 1. Dependency install — PASS

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && npm ci 2>&1 | tail -3
```

**Exit/result:** exit 0.

**Captured output**
```text
  run `npm fund` for details

found 0 vulnerabilities
```

## 2. TypeScript — PASS

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && npx tsc --noEmit 2>&1 | tail -20
```

**Exit/result:** exit 0; no TypeScript diagnostics were emitted (empty output).

## 3. Lint — PASS with P2

`package.json` lint script: `eslint .`

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && npm run lint 2>&1
```

**Exit/result:** exit 0. **0 errors, 1 warning.**

**Exact diagnostic**
```text
/home/user/workspace/harboriq_repo/frontend/src/main.tsx
  24:7  warning  Fast refresh only works when a file has exports. Move your component(s) to a separate file  react-refresh/only-export-components

✖ 1 problem (0 errors, 1 warning)
```

**Finding — P2:** `src/main.tsx:24` has a React Fast Refresh warning. It does not block production output, but should be resolved or explicitly suppressed to keep CI warning-free.

## 4. Unit/integration tests — PASS

`package.json` test script: `vitest run`

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && npm run test -- --run 2>&1
```

**Exit/result:** exit 0.

**Pass/fail counts**
```text
Test Files  31 passed (31)
Tests       128 passed (128)
Duration    55.51s
```

**Failing/flaky tests:** none observed; no test failed. A single execution cannot prove that a test is non-flaky.

**Non-failing runner output:** Vitest/jsdom emitted `Not implemented: navigation to another Document` three times; it did not cause a failure. Treat this as **P2 test-output noise**—mock or avoid the navigation path if clean test logs are required.

## 5. Production build — PASS with P2

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && npm run build 2>&1 | tail -10
```

**Exit/result:** exit 0. The captured tail included:
```text
✓ built in 2.98s

PWA v1.3.0
mode      generateSW
precache  17 entries (1065.85 KiB)
files generated
  dist/sw.js
  dist/workbox-abeb32eb.js
```

A follow-up build-output capture identified the bundle warning (build still exited 0):
```text
[plugin builtin:vite-reporter]
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
```

The main JavaScript output was `dist/assets/index-BjDmQRU0.js` at **1,006.65 kB minified / 284.42 kB gzip**.

**Finding — P2:** code-split the large application bundle (or document an approved budget exception) before performance-sensitive rollout. This is a Vite warning, not a failed build.

## 6. PWA readiness — PASS

### Present

- `vite.config.ts` configures `VitePWA` with `registerType: "autoUpdate"`, standalone display, `/field` start URL, scope `/`, theme/background colors, and 192/512/maskable icons.
- The production build generated `dist/manifest.webmanifest`, `dist/sw.js`, and `dist/workbox-abeb32eb.js`.
- `src/main.tsx` imports `registerSW` from `virtual:pwa-register` and calls `registerSW({ immediate: true })` when service workers are supported.
- Workbox precaches the app shell and sets `navigateFallback: "index.html"`; `/api/` uses `NetworkOnly` rather than stale API caching.
- Field workflows have IndexedDB job caching (`src/lib/offlineDb.ts`, consumed by `useFieldJobs`) and an offline action queue (`src/lib/offlineQueue.ts`, replayed by `useOfflineQueue` on mount and browser `online`).
- `index.html` includes iOS standalone/add-to-home-screen metadata and an Apple touch icon.

### Missing / limitations

- No source `public/manifest.json` exists; this is intentional in this implementation because VitePWA emits `dist/manifest.webmanifest` at build time. It is **not a blocker**.
- API responses are intentionally not cached by the service worker; offline job data depends on the application-level IndexedDB cache. This is documented in configuration and is appropriate only for implemented field-data flows.
- Browser/device offline-install behavior was not manually exercised in this read-only gate; execute a device/browser smoke test before broad rollout.

**PWA launch-gate classification:** no repository-detectable P0/P1 defect.

## 7. Mobile readiness — FAIL (P1)

### Ready in the repository

- `capacitor.config.ts` sets `appId: "com.harboriq.app"` (confirmed), `appName: "HarborIQ"`, and `webDir: "dist"`.
- Native platform folders exist: `frontend/android/` and `frontend/ios/`.
- The configuration uses HTTPS schemes and disables Android cleartext/mixed content.
- `.github/workflows/mobile.yml` builds the web assets, synchronizes Capacitor, produces an Android release `.aab`, and performs an iOS Release compile check.

### Android signing/store prerequisites

The workflow uses `vars.ANDROID_SIGNING_READY == 'true'` to enable signing and expects all four secrets:

1. `ANDROID_KEYSTORE_BASE64`
2. `ANDROID_KEYSTORE_PASSWORD`
3. `ANDROID_KEY_ALIAS`
4. `ANDROID_KEY_PASSWORD`

It also relies on a `PROD_API_URL` repository variable (with `https://api.harboriq.app` as fallback). Repository inspection cannot reveal whether GitHub secrets/variables or a Google Play Console account/upload key are actually configured. If signing is not ready, the workflow intentionally emits an unsigned release build; it also uploads an artifact but has no Play Console upload/deployment step.

### iOS store prerequisites

The iOS workflow runs only:
```text
xcodebuild ... CODE_SIGNING_ALLOWED=NO build
```
It has no archive, signing, App Store Connect/TestFlight upload, certificate/provisioning-profile, or App Store Connect API-key setup. The workflow comment explicitly defers those until an Apple Developer account and credentials are available.

**Finding — P1 (mobile-store launch blocker):** iOS is not submit-ready, and Android signing/Play configuration is unverifiable and not automated. Before mobile-store launch, provision the Apple Developer Program/App Store Connect setup and release signing/upload pipeline; configure and safely validate the four Android secrets, `ANDROID_SIGNING_READY`, production API variable, Play Console app/account, and release upload process.

## 8. Production TODO/FIXME/placeholder/mock scan — PASS

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && find src -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' \) ! -name '*.test.*' ! -name '*.spec.*' -print0 | xargs -0 -r grep -nEi 'TODO|FIXME|placeholder|mock[ _-]?(data|api|user|job|invoice|customer|client|item|response|service)?|hardcoded|dummy|sample data|fake data' || true
```

The scan found no production `TODO`, `FIXME`, mock-data, dummy-data, sample-data, or hardcoded-data marker. The only application-path matches were normal form `placeholder` attributes:

- `src/pages/CustomersPage.tsx:57` — search input
- `src/pages/LoginPage.tsx:85` — MFA/recovery-code input
- `src/pages/AcceptInvitePage.tsx:83` — invited-user name
- `src/pages/SecuritySettingsPage.tsx:225` — verification code
- `src/pages/MessagesPage.tsx:129` and `src/portal/PortalMessages.tsx:90` — message inputs
- `src/pages/TeamPage.tsx:229,237` — skills/address inputs
- `src/pages/VendorsPage.tsx:60` — vendor search
- `src/pages/InventoryPage.tsx:93,124` — SKU/search inputs

These are user-interface affordances, not production mock data or launch problems. **No severity assigned.**

## 9. Accessibility quick check — PASS with P2 caveat

**Exact command**
```sh
cd /home/user/workspace/harboriq_repo/frontend && rg -n '<html[^>]*\blang=' index.html && rg -n -U '<img\b[^>]*>|<img\b[\s\S]{0,300}?>' src/pages --glob '*.{tsx,jsx}' && rg -n '\balt\s*=' src/pages --glob '*.{tsx,jsx}'
```

**Rough-signal result**

- `index.html:2` has `<html lang="en">`.
- One `<img>` was found in `src/pages/JobDetailPage.tsx:510`; it has `alt={att.kind}` at line 512.
- No page image lacked an observed `alt` attribute in this basic search.

**Finding — P2 (coverage gap):** `package.json` has no `eslint-plugin-jsx-a11y`, `axe-core`, or `@axe-core/react`, and ESLint has no accessibility rule set. This simple static signal is not a substitute for keyboard, contrast, semantic-control, screen-reader, and automated axe checks. Add automated accessibility coverage before declaring WCAG conformance.

## Consolidated findings and release actions

| Severity | Finding | Required launch action |
|---|---|---|
| **P1** | Native store release path is incomplete: iOS is unsigned compile-only; Android signing/Play account readiness cannot be established from source and deployment is manual. | Complete store accounts, credentials, signing, archive/upload/release flows, then execute signed-device/store smoke tests. |
| **P2** | One React Fast Refresh lint warning at `src/main.tsx:24`. | Resolve or intentionally suppress with rationale. |
| **P2** | Main production JavaScript chunk exceeds Vite's 500 kB minified warning threshold (1,006.65 kB). | Code-split/lazy-load routes or approve a measured budget exception. |
| **P2** | Tests pass but emit three jsdom navigation-not-implemented lines. | Remove or mock the navigation behavior to keep tests diagnostic-clean. |
| **P2** | No automated accessibility lint/axe coverage detected. | Add automated a11y checks and manual keyboard/screen-reader validation. |

**P0 findings:** none observed in the requested frontend gates.
