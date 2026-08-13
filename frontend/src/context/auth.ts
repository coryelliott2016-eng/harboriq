import { createContext, useContext } from "react";
import type { User } from "../types/api";

/** Returned by `login()` when the account has MFA active -- there are no
 * real tokens yet, so the caller must render a second-factor prompt and
 * then call `loginMfa()` with the code the user enters. */
export interface MfaLoginChallenge {
  preAuthToken: string;
}

export interface AuthContextValue {
  user: User | null;
  /** True while the initial GET /auth/me hydration is in flight. */
  loading: boolean;
  /** Resolves once logged in. Resolves to an `MfaLoginChallenge` instead,
   * WITHOUT logging in, if the account requires a second factor -- pass it
   * to `loginMfa()` once the user has entered their code. */
  login: (email: string, password: string) => Promise<MfaLoginChallenge | void>;
  loginMfa: (preAuthToken: string, code: string) => Promise<void>;
  signup: (input: {
    company_name: string;
    email: string;
    password: string;
    full_name?: string;
  }) => Promise<void>;
  acceptInvite: (token: string, input: { password: string; full_name?: string }) => Promise<void>;
  logout: () => Promise<void>;
}

/** The context object itself lives here (not in AuthContext.tsx) so the
 * provider file only exports a component -- this keeps React Fast Refresh
 * working (react-refresh/only-export-components). */
export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export const OPERATIONS_ROLES: User["role"][] = ["owner", "admin", "office"];

export function canManageOperations(role: User["role"] | undefined): boolean {
  return !!role && OPERATIONS_ROLES.includes(role);
}

export function canManageUsers(role: User["role"] | undefined): boolean {
  return role === "owner" || role === "admin";
}
