import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Problem, setActiveFirm } from "./api";
import type { FirmRole, Me, Membership } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  firm: Membership | null;
  role: FirmRole | null;
  isStaff: boolean;
  switchFirm: (firmId: string) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);
const FIRM_KEY = "dam.activeFirm";

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api.me();
      } catch (e) {
        if (e instanceof Problem && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  const [firmId, setFirmId] = useState<string | null>(() => {
    try {
      return localStorage.getItem(FIRM_KEY);
    } catch {
      return null;
    }
  });

  const me = meQuery.data ?? null;
  const firm = useMemo(() => {
    if (!me) return null;
    return me.memberships.find((m) => m.firm_id === firmId) ?? me.memberships[0] ?? null;
  }, [me, firmId]);

  useEffect(() => {
    setActiveFirm(firm?.firm_id ?? null);
    if (firm) {
      try {
        localStorage.setItem(FIRM_KEY, firm.firm_id);
      } catch {
        /* ignore */
      }
    }
  }, [firm]);

  const value: AuthState = {
    me,
    loading: meQuery.isLoading,
    firm,
    role: firm?.role ?? null,
    isStaff: firm?.role === "admin" || firm?.role === "staff",
    switchFirm: (id) => {
      setFirmId(id);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
    logout: async () => {
      await api.logout();
      setActiveFirm(null);
      qc.clear();
      await qc.invalidateQueries({ queryKey: ["me"] });
    },
  };
  // Keep the header in sync before children render their first queries.
  setActiveFirm(firm?.firm_id ?? null);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
