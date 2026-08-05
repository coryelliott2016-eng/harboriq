import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../lib/api";
import { Button, ErrorBanner, Field, inputClass } from "../components/ui";

export function LoginPage() {
  const { user, login, loginMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Set once POST /auth/login comes back with `mfa_required: true`. Its
  // presence, rather than the credentials form, is what decides which step
  // renders below -- see the second `if` below.
  const [preAuthToken, setPreAuthToken] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  if (user) {
    const from = (location.state as { from?: Location })?.from;
    return <Navigate to={from?.pathname ?? "/"} replace />;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await login(email, password);
      if (result) {
        // Second factor required -- render the code prompt instead of
        // navigating away. No tokens exist yet.
        setPreAuthToken(result.preAuthToken);
        return;
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to log in. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfaSubmit(e: FormEvent) {
    e.preventDefault();
    if (!preAuthToken) return;
    setError(null);
    setSubmitting(true);
    try {
      await loginMfa(preAuthToken, mfaCode.trim());
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Unable to verify that code. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (preAuthToken) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">Two-factor verification</h1>
          <p className="mt-1 text-sm text-slate-500">
            Enter the 6-digit code from your authenticator app, or one of your backup
            codes.
          </p>

          <form onSubmit={handleMfaSubmit} className="mt-6 flex flex-col gap-4">
            {error && <ErrorBanner message={error} />}
            <Field label="Authentication code">
              <input
                type="text"
                required
                autoFocus
                inputMode="text"
                autoComplete="one-time-code"
                placeholder="123456 or XXXX-XXXX"
                className={inputClass}
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
              />
            </Field>
            <Button type="submit" disabled={submitting || !mfaCode.trim()} className="mt-2 w-full">
              {submitting ? "Verifying…" : "Verify and log in"}
            </Button>
            <button
              type="button"
              className="text-center text-sm text-slate-500 underline"
              onClick={() => {
                setPreAuthToken(null);
                setMfaCode("");
                setError(null);
              }}
            >
              Back to login
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Log in to HarborIQ</h1>
        <p className="mt-1 text-sm text-slate-500">Marine service operations, in one place.</p>

        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
          <Field label="Email">
            <input
              type="email"
              required
              className={inputClass}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              required
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </Field>
          <Button type="submit" disabled={submitting} className="mt-2 w-full">
            {submitting ? "Logging in…" : "Log in"}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          New to HarborIQ?{" "}
          <Link to="/signup" className="font-medium text-slate-900 underline">
            Create your company account
          </Link>
        </p>
      </div>
    </div>
  );
}
