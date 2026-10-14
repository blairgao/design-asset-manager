import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActiveFirm } from "./api";
import type { FirmRole, Me, Membership } from "./types";

interface ViewerState {
  me: Me | null;
  loading: boolean;
  error: unknown;
  firm: Membership | null;
  role: FirmRole | null;
  isStaff: boolean;
  switchFirm: (firmId: string) => void;
}

const ViewerContext = createContext<ViewerState | null>(null);
const FIRM_KEY = "dam.activeFirm";

/** The current user. There is no sign-in yet: the API answers /me with a fixed local user. */
export function ViewerProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
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

  const value: ViewerState = {
    me,
    loading: meQuery.isLoading,
    error: meQuery.error,
    firm,
    role: firm?.role ?? null,
    isStaff: firm?.role === "admin" || firm?.role === "staff",
    switchFirm: (id) => {
      setFirmId(id);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  };
  // Keep the header in sync before children render their first queries.
  setActiveFirm(firm?.firm_id ?? null);
  return <ViewerContext.Provider value={value}>{children}</ViewerContext.Provider>;
}

export function useViewer(): ViewerState {
  const ctx = useContext(ViewerContext);
  if (!ctx) throw new Error("useViewer outside ViewerProvider");
  return ctx;
}
