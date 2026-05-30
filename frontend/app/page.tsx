"use client";

import { useState } from "react";
import { useTransactions, type Transaction } from "./context/TransactionContext";
import { WebRepBadge } from "./components/WebRepBadge";
import { WebRepDetailModal } from "./components/WebRepDetailModal";

const riskRowClasses: Record<string, string> = {
  HIGH: "bg-red-50 border-l-4 border-red-500",
  MEDIUM: "bg-yellow-50 border-l-4 border-yellow-500",
  LOW: "bg-green-50 border-l-4 border-green-500",
};

const badgeClasses: Record<string, string> = {
  HIGH: "bg-red-600 text-white",
  MEDIUM: "bg-yellow-500 text-white",
  LOW: "bg-green-600 text-white",
};

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return <span className="text-gray-400 text-xs">pending</span>;
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-semibold ${badgeClasses[level] || "bg-gray-400 text-white"}`}
    >
      {level}
    </span>
  );
}

function truncate(s: string | null, n = 90) {
  if (!s) return "—";
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="bg-white rounded-lg shadow p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className={`text-3xl font-bold mt-1 ${accent || "text-gray-900"}`}>
        {value}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { transactions, newIds, simulate, stats } = useTransactions();
  const [openTxnId, setOpenTxnId] = useState<string | null>(null);

  return (
    <main className="min-h-screen w-full bg-gray-50 p-8 text-gray-900">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Sentinel Dashboard</h1>
          <p className="text-gray-600 mt-1">Autonomous real-time fraud detection</p>
        </div>
        <button
          onClick={simulate}
          className="bg-red-600 hover:bg-red-700 text-white font-semibold px-4 py-2 rounded shadow"
        >
          Simulate Suspicious Transaction
        </button>
      </header>

      <section className="grid grid-cols-3 gap-4 mb-6">
        <StatCard label="Scanned" value={stats.total} />
        <StatCard label="HIGH risk detected" value={stats.high} accent="text-red-600" />
        <StatCard label="Accounts frozen" value={stats.frozen} accent="text-orange-600" />
      </section>

      <section className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-100">
            <tr className="text-left text-gray-600">
              <th className="px-4 py-3">ID</th>
              <th className="px-4 py-3">User</th>
              <th className="px-4 py-3">Amount</th>
              <th className="px-4 py-3">Location</th>
              <th className="px-4 py-3">Risk</th>
              <th className="px-4 py-3">Web Rep</th>
              <th className="px-4 py-3">Explanation</th>
              <th className="px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody>
            {transactions.length === 0 && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-gray-400">
                  No transactions yet — click &ldquo;Simulate Suspicious Transaction&rdquo;.
                </td>
              </tr>
            )}
            {transactions.map((t: Transaction) => (
              <tr
                key={t.id}
                className={`border-b ${riskRowClasses[t.risk_level || ""] || ""} ${
                  newIds.has(t.id) ? "animate-fade-in" : ""
                }`}
              >
                <td className="px-4 py-3 font-mono text-xs">{t.id}</td>
                <td className="px-4 py-3">{t.user_id}</td>
                <td className="px-4 py-3">${t.amount.toFixed(2)}</td>
                <td className="px-4 py-3">{t.location}</td>
                <td className="px-4 py-3">
                  <RiskBadge level={t.risk_level} />
                </td>
                <td
                  className="px-4 py-3 cursor-pointer"
                  onClick={() => setOpenTxnId(t.id)}
                >
                  <WebRepBadge score={t.web_rep_score} cached={t.web_rep_cached} />
                </td>
                <td className="px-4 py-3 text-gray-700">{truncate(t.explanation)}</td>
                <td className="px-4 py-3 text-xs">
                  {t.action_taken === "account_frozen" ? (
                    <span className="text-orange-700 font-semibold">Account frozen</span>
                  ) : (
                    <span className="text-gray-400">{t.action_taken || "—"}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {openTxnId && (
        <WebRepDetailModal txnId={openTxnId} onClose={() => setOpenTxnId(null)} />
      )}
    </main>
  );
}
