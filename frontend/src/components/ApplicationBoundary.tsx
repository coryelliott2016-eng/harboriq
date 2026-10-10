import type { ReactNode } from "react";
import { useMatch } from "react-router-dom";
import { AuthProvider } from "../context/AuthContext";

export function ApplicationBoundary({ children }: { children: ReactNode }) {
  const publicLab = useMatch("/intelligence-lab");

  // Router matching also covers client navigation, hash routing, case, and
  // trailing slashes without initiating staff session hydration in the lab.
  return publicLab ? <>{children}</> : <AuthProvider>{children}</AuthProvider>;
}
