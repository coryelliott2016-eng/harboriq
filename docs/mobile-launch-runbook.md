# HarborIQ Mobile Launch Runbook (App Store + Google Play)

Status: Capacitor shell scaffolded (`frontend/ios`, `frontend/android`), CI
builds wired (`.github/workflows/mobile.yml`). Blocked on the business
prerequisites below — work through them in order; tracks A/B/C can run in
parallel.

The app identifier is `com.harboriq.app`. It is registered in both native
projects and **can never change after first store submission**.

---

## Track A — Business prerequisites (owner: Cory)

### A1. D-U-N-S number (blocks BOTH store enrollments)
- Both Apple and Google organization accounts require a D-U-N-S number for
  HarborIQ, Inc. (the legal entity — DBAs are not accepted by Apple).
- Free from Dun & Bradstreet: <https://developer.apple.com/enroll/duns-lookup/>
  (Apple's lookup tool also lets you request one). Typical 1–5 business
  days; can take up to 30.
- Source: [Apple enrollment requirements](https://developer.apple.com/help/account/membership/program-enrollment/)

### A2. Apple Developer Program — organization ($99/year)
- Requirements: legal entity, D-U-N-S, authority to sign for the company,
  **work email on a HarborIQ-owned domain**, and a **publicly reachable
  website on that domain** (A3 satisfies this).
- Enroll at <https://developer.apple.com/programs/enroll/> with an Apple ID
  (2FA enabled, legal name). Org verification: ~1–2 weeks.

### A3. Google Play Console — organization ($25 one-time)
- Enroll at <https://play.google.com/console/signup> with a Google account
  (2-Step Verification on). Organization accounts need the D-U-N-S number
  and skip the personal-account closed-testing rule (12 testers / 14 days).
- Verification can take 1–4 weeks.
  Source: [Play Console signup](https://support.google.com/googleplay/android-developer/answer/6112435)

### A4. Legal/compliance pages (required by both stores)
- **Privacy policy URL** — mandatory for both listings; must cover the data
  the app collects (account data, job/customer records, photos, location
  pings, offline-cached data).
- **Support URL + support email.**
- Apple **App Privacy** questionnaire and Google **Data safety** form must
  match the privacy policy exactly — inconsistencies are a common rejection.

---

## Track B — Production deployment (owner: agent, next task)

The mobile binaries bundle the SPA but talk to the real API over HTTPS.
Before store review:

1. Deploy backend + frontend to a public HTTPS domain (e.g.
   `app.harboriq.com` / `api.harboriq.com`).
2. Set the GitHub repository **variable** `PROD_API_URL` to the API origin —
   the mobile workflow bakes it into the binaries.
3. Add the Capacitor WebView origin to backend CORS:
   `CORS_ALLOW_ORIGINS=https://app.harboriq.com,https://localhost`
   (`https://localhost` is the bundled-app origin on both platforms).
4. Store reviewers need a **working demo account** — seed a demo tenant with
   realistic data and put the credentials in the review notes.

---

## Track C — Signing & store submission (after A + B)

### C1. Android (can be done entirely from CI — no local tooling needed)
1. Generate an upload keystore (once, keep it safe):
   `keytool -genkey -v -keystore upload-keystore.jks -alias harboriq-upload -keyalg RSA -keysize 2048 -validity 10000`
2. Add GitHub **secrets**: `ANDROID_KEYSTORE_BASE64` (`base64 -w0 upload-keystore.jks`),
   `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`;
   set repo **variable** `ANDROID_SIGNING_READY=true`.
3. Run the *Mobile builds* workflow → download the signed `.aab` artifact.
4. In Play Console: create the app, enroll in **Play App Signing**, upload
   the `.aab` to Internal testing first, complete Data safety + content
   rating, then promote to Production.

### C2. iOS (built on GitHub's macOS/Xcode 26 runners — no Mac needed)
Apple requires Xcode 26 builds since 2026-04-28
([Capgo](https://capgo.app/blog/xcode-26-requirement-for-capacitor-apps/));
the CI job already targets `macos-26`.
1. In the Apple Developer portal, create an **App Store Connect API key**
   (Users and Access → Integrations) — this lets CI sign and upload without
   a Mac.
2. Add secrets: `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8` (the .p8 file
   contents), plus a distribution certificate (`IOS_CERT_P12_BASE64`,
   `IOS_CERT_PASSWORD`).
3. Extend the `ios` job with fastlane (`match`/`gym`/`pilot`) or
   `xcodebuild archive` + `xcrun altool` to archive, sign, and push to
   TestFlight. (Do this as a follow-up PR once the secrets exist.)
4. TestFlight → App Store review. **Guideline 4.2 note:** the listing should
   emphasize native capabilities (offline field mode with encrypted local
   vault, camera capture on jobs, installable field-tech workflow) — thin
   web wrappers get rejected; genuinely offline-capable field tools pass.

### C3. Store listing assets (both)
- App name: HarborIQ. Short + full descriptions (marine service management).
- Screenshots: iPhone 6.7"/6.9" and iPad 13" for Apple; phone + 7"/10"
  tablet for Play. Feature graphic 1024×500 (Play).
- Icon 1024×1024 already generated (`frontend/assets/icon.png`).
- Category: Business. Content rating: Everyone.

---

## What is already done in this repo

| Item | Where |
|---|---|
| Capacitor 8 config (bundled SPA, HTTPS-only, no cleartext) | `frontend/capacitor.config.ts` |
| Native iOS project (Xcode workspace) | `frontend/ios/` |
| Native Android project (Gradle) | `frontend/android/` |
| App icons + splash (light/dark), all densities | generated from `frontend/assets/` |
| Camera/photo permission strings (App Store requirement) | `ios/App/App/Info.plist` |
| Android media permissions | `android/app/src/main/AndroidManifest.xml` |
| Export-compliance flag (`ITSAppUsesNonExemptEncryption=false` — HTTPS-only exemption) | `Info.plist` |
| CI: Android release .aab + iOS Xcode 26 compile check | `.github/workflows/mobile.yml` |

Native plugins installed and available to the app: `@capacitor/app`,
`@capacitor/camera`, `@capacitor/network`, `@capacitor/splash-screen`,
`@capacitor/status-bar`. Push notifications (`@capacitor/push-notifications`)
are deliberately deferred until the Apple account exists (APNs keys) and a
Firebase project is set up (FCM) — tracked as a follow-up.
