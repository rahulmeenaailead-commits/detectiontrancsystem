"use client";

import axios from "axios";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_SENTINEL_API_KEY || "sentinel-dev-key";

const api = axios.create({
  baseURL: API,
  headers: { "X-API-Key": API_KEY },
  timeout: 2500,
});

export type Transaction = {
  id: string;
  user_id: string;
  amount: number;
  location: string;
  timestamp: string;
  merchant: string;
  fraud_score: number | null;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | null;
  explanation: string | null;
  account_frozen: boolean;
  action_taken: string | null;
  web_rep_score: number | null;
  web_rep_cached: boolean | null;
  web_rep_top_signals: string[] | null;
};

type Ctx = {
  transactions: Transaction[];
  newIds: Set<string>;
  refresh: () => Promise<void>;
  simulate: () => Promise<void>;
  stats: { total: number; high: number; frozen: number };
  error: string | null;
};

const TransactionContext = createContext<Ctx | null>(null);

const SUSPICIOUS_LOCATIONS = [
  "Port City A",
  "Coastal Hub B",
  "Trade Zone C",
  "Anonymous Region D",
];
const SUSPICIOUS_MERCHANTS = [
  "Unknown Wire Transfer",
  "Crypto Exchange XYZ",
  "Offshore Holdings Ltd",
  "Anonymous P2P",
];

function randomSuspicious() {
  // Each simulated fraud comes from a *fresh* user id. A HIGH-risk verdict
  // autonomously freezes that user's account, and a frozen account rejects any
  // further /analyze calls with HTTP 423. Reusing a single id (e.g. "u1") made
  // the Simulate button a one-shot: the first click froze the user, every later
  // click 423'd. A unique id per click keeps the button repeatable and lets the
  // "Frozen Accounts" counter climb as new fraud is caught.
  const uid = `sim-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e4)}`;
  return {
    id: `tx-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    user_id: uid,
    amount: 5000 + Math.floor(Math.random() * 15000),
    location:
      SUSPICIOUS_LOCATIONS[Math.floor(Math.random() * SUSPICIOUS_LOCATIONS.length)],
    timestamp: new Date().toISOString(),
    merchant:
      SUSPICIOUS_MERCHANTS[Math.floor(Math.random() * SUSPICIOUS_MERCHANTS.length)],
  };
}

export function TransactionProvider({ children }: { children: React.ReactNode }) {
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const knownIds = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get<Transaction[]>("/transactions");
      const fresh = data.filter((t) => !knownIds.current.has(t.id)).map((t) => t.id);
      if (fresh.length) {
        setNewIds(new Set(fresh));
        fresh.forEach((id) => knownIds.current.add(id));
        setTimeout(() => setNewIds(new Set()), 700);
      }
      data.forEach((t) => knownIds.current.add(t.id));
      setTransactions(data);
      setError(null);
    } catch (e: unknown) {
      const status = axios.isAxiosError(e) ? e.response?.status : undefined;
      if (status === 401 || status === 403) {
        setError("Auth failed — check NEXT_PUBLIC_SENTINEL_API_KEY.");
      } else {
        setError("Backend unreachable — retrying…");
      }
    }
  }, []);

  const simulate = useCallback(async () => {
    try {
      await api.post("/analyze", randomSuspicious());
    } catch (e) {
      // Don't let a failed injection wedge the UI; still refresh so the table
      // reflects current backend state.
      console.error("Simulate failed", e);
    } finally {
      await refresh();
    }
  }, [refresh]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  const stats = {
    total: transactions.length,
    high: transactions.filter((t) => t.risk_level === "HIGH").length,
    frozen: new Set(
      transactions.filter((t) => t.account_frozen).map((t) => t.user_id),
    ).size,
  };

  return (
    <TransactionContext.Provider
      value={{ transactions, newIds, refresh, simulate, stats, error }}
    >
      {children}
    </TransactionContext.Provider>
  );
}

export function useTransactions() {
  const ctx = useContext(TransactionContext);
  if (!ctx) throw new Error("useTransactions must be used within TransactionProvider");
  return ctx;
}
