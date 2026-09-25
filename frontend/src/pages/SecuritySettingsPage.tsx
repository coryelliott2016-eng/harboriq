import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { QRCodeSVG } from "qrcode.react";
import { mfaApi } from "../lib/services";
import { ApiError } from "../lib/api";
import type { MfaEnrollResponse, MfaStatus } from "../types/api";
import { Button, Card, ErrorBanner, Field, Spinner, inputClass } from "../components/ui";

// Self-service TOTP MFA management (Phase 16) -- enroll -> confirm ->
// (optionally later) disable. Every request here rides the caller's own
// normal session; there is no admin-on-behalf-of-another-user path, which
// mirrors the backend (app/api/v1/routes/users.py's `/users/me/mfa/*`
// endpoints only ever act on `get_current_user()`, never a path param).
export function SecuritySettingsPage() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Enrollment-in-progress state (pending confirm).
  const [enrollment, setEnrollment] = useState<MfaEnrollResponse | null>(null);
  const [confirmCode, setConfirmCode] = useState("");
  const [confirming, setConfirming] = useState(false);

  // Just-confirmed backup codes, shown exactly once.
  const [freshBackupCodes, setFreshBackupCodes] = useState<string[] | null>(null);

  // Disable flow.
  const [disabling, setDisabling] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");
  const [disableSubmitting, setDisableSubmitting] = useState(false);

  async function refreshStatus() {
    const s = await mfaApi.status();
    setStatus(s);
  }

  useEffect(() => {
    (async () => {
      try {
        await refreshStatus();
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Unable to load MFA status.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  async function handleStartEnroll() {
    setError(null);
    try {
      const resp = await mfaApi.enroll();
      setEnrollment(resp);
      setConfirmCode("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to start enrollment.");
    }
  }

  async function handleConfirm(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setConfirming(true);
    try {
      const resp = await mfaApi.confirm(confirmCode.trim());
      setFreshBackupCodes(resp.backup_codes);
      setEnrollment(null);
      setConfirmCode("");
      await refreshStatus();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That code didn't match. Please try again.",
      );
    } finally {
      setConfirming(false);
    }
  }

  async function handleDisable(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setDisableSubmitting(true);
    try {
      await mfaApi.disable(disablePassword);
      setDisabling(false);
      setDisablePassword("");
      setFreshBackupCodes(null);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to disable two-factor auth.");
    } finally {
      setDisableSubmitting(false);
    }
  }

  if (loading) return <Spinner label="Loading security settings…" />;

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Security</h1>
        <p className="mt-1 text-sm text-slate-500">
          Two-factor authentication adds a second step to your login using an
          authenticator app (Google Authenticator, 1Password, Authy, etc.).
        </p>
      </div>

      {error && <ErrorBanner message={error} />}

      {/* One-time backup-codes display, right after a successful confirm. */}
      {freshBackupCodes && (
        <Card className="border-amber-300 bg-amber-50 p-5">
          <h2 className="text-sm font-semibold text-amber-900">Save your backup codes</h2>
          <p className="mt-1 text-sm text-amber-800">
            Each code can be used once to log in if you lose access to your authenticator
            app. Store them somewhere safe — this is the only time they're shown.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-sm text-amber-950">
            {freshBackupCodes.map((code) => (
              <div key={code} className="rounded bg-white px-2 py-1 text-center">
                {code}
              </div>
            ))}
          </div>
          <Button className="mt-4" onClick={() => setFreshBackupCodes(null)}>
            I've saved these codes
          </Button>
        </Card>
      )}

      {/* Case 1: MFA already enabled, no enrollment in progress. */}
      {status?.mfa_enabled && !enrollment && !freshBackupCodes && (
        <Card className="p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-slate-900">
                Two-factor authentication is on
              </p>
              <p className="mt-1 text-sm text-slate-500">
                {status.remaining_backup_codes} unused backup code
                {status.remaining_backup_codes === 1 ? "" : "s"} remaining.
              </p>
            </div>
            {!disabling && (
              <Button variant="secondary" onClick={() => setDisabling(true)}>
                Turn off
              </Button>
            )}
          </div>

          {disabling && (
            <form onSubmit={handleDisable} className="mt-4 flex flex-col gap-3 border-t border-slate-200 pt-4">
              <p className="text-sm text-slate-600">
                Enter your password to confirm turning off two-factor authentication.
              </p>
              <Field label="Password">
                <input
                  type="password"
                  required
                  autoComplete="current-password"
                  className={inputClass}
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                />
              </Field>
              <div className="flex gap-2">
                <Button type="submit" disabled={disableSubmitting}>
                  {disableSubmitting ? "Turning off…" : "Confirm turn off"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setDisabling(false);
                    setDisablePassword("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </Card>
      )}

      {/* Case 2: not enabled, no enrollment started yet. */}
      {status && !status.mfa_enabled && !enrollment && !freshBackupCodes && (
        <Card className="p-5">
          <p className="text-sm font-medium text-slate-900">
            Two-factor authentication is off
          </p>
          <p className="mt-1 text-sm text-slate-500">
            Turn it on to require a code from your phone in addition to your password.
          </p>
          <Button className="mt-4" onClick={() => void handleStartEnroll()}>
            Set up two-factor authentication
          </Button>
        </Card>
      )}

      {/* Case 3: enrollment started, awaiting confirm. */}
      {enrollment && (
        <Card className="p-5">
          <p className="text-sm font-medium text-slate-900">Scan this QR code</p>
          <p className="mt-1 text-sm text-slate-500">
            Scan it with your authenticator app, then enter the 6-digit code it shows to
            finish setup.
          </p>
          <div className="mt-4 flex justify-center rounded-md bg-white p-4">
            <QRCodeSVG value={enrollment.otpauth_uri} size={192} />
          </div>
          <p className="mt-3 text-center text-xs text-slate-500">
            Can't scan? Enter this code manually:{" "}
            <span className="font-mono font-medium text-slate-700">{enrollment.secret}</span>
          </p>

          <form onSubmit={handleConfirm} className="mt-4 flex flex-col gap-3 border-t border-slate-200 pt-4">
            <Field label="6-digit code">
              <input
                type="text"
                required
                // This field only mounts after the user clicks "Enable MFA",
                // replacing the setup step with the confirmation form; the
                // focus jump follows their own action rather than surprising
                // them on initial page load, matching the OTP-entry pattern
                // used by GitHub/Google's own MFA setup screens.
                // eslint-disable-next-line jsx-a11y/no-autofocus
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                className={inputClass}
                value={confirmCode}
                onChange={(e) => setConfirmCode(e.target.value)}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="submit" disabled={confirming || !confirmCode.trim()}>
                {confirming ? "Verifying…" : "Verify and turn on"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setEnrollment(null)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}
    </div>
  );
}
