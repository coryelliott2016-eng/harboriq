import { useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/auth";
import { ApiError } from "../lib/api";
import { Button, ErrorBanner, Field, inputClass } from "../components/ui";

export function SignupPage() {
  const { user, signup } = useAuth();
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!agreedToTerms) {
      setError("You must agree to the Terms of Service and Privacy Policy to create an account.");
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await signup({ company_name: companyName, email, password, full_name: fullName || undefined });
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unable to sign up. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Set up your shop</h1>
        <p className="mt-1 text-sm text-slate-500">
          Creates your company and your owner account.
        </p>

        <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
          <Field label="Company name">
            <input
              required
              className={inputClass}
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
            />
          </Field>
          <Field label="Your name">
            <input
              className={inputClass}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </Field>
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
              minLength={12}
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <p className="text-xs text-slate-400">At least 12 characters.</p>
          <label className="flex items-start gap-2 text-xs text-slate-500">
            <input
              type="checkbox"
              required
              checked={agreedToTerms}
              onChange={(e) => setAgreedToTerms(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-slate-300"
            />
            <span>
              I agree to the{" "}
              <a
                href="https://harboriq.com/#/terms"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-slate-700 underline"
              >
                Terms of Service
              </a>{" "}
              and{" "}
              <a
                href="https://harboriq.com/#/privacy"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-slate-700 underline"
              >
                Privacy Policy
              </a>
              .
            </span>
          </label>
          <Button type="submit" disabled={submitting || !agreedToTerms} className="mt-2 w-full">
            {submitting ? "Creating account…" : "Create account"}
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-slate-500">
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-slate-900 underline">
            Log in
          </Link>
        </p>
      </div>
    </div>
  );
}
