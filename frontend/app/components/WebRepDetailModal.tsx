"use client";
import { useEffect, useState } from "react";

type WebRepDetail = {
  merchant: string;
  score: number | null;
  mode: string;
  signals: string[];
  top_results: { title: string; snippet: string; url: string; source_domain: string }[];
  fetched_at: string | null;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const KEY = process.env.NEXT_PUBLIC_SENTINEL_API_KEY || "sentinel-dev-key";

export function WebRepDetailModal({
  txnId,
  onClose,
}: {
  txnId: string;
  onClose: () => void;
}) {
  const [data, setData] = useState<WebRepDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/transactions/${txnId}/web-rep`, { headers: { "X-API-Key": KEY } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setData)
      .catch((e) => setErr(String(e)));
  }, [txnId]);

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold">Web Reputation</h2>
          <button onClick={onClose} className="text-gray-500">
            ✕
          </button>
        </div>
        {err && <p className="text-red-600">Error: {err}</p>}
        {!data && !err && <p>Loading…</p>}
        {data && (
          <>
            <p className="text-sm mb-2">
              <strong>{data.merchant}</strong> — score {data.score ?? "n/a"} ({data.mode})
            </p>
            <p className="text-xs text-gray-500 mb-3">Fetched: {data.fetched_at ?? "never"}</p>
            <div className="mb-3">
              <strong>Signals:</strong>{" "}
              {data.signals.length ? data.signals.join(", ") : "none"}
            </div>
            <ul className="space-y-3">
              {data.top_results.map((r, i) => (
                <li key={i} className="border-b pb-2">
                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-600 font-medium"
                  >
                    {r.title}
                  </a>
                  <p className="text-xs text-gray-500">{r.source_domain}</p>
                  <p className="text-sm text-gray-700">{r.snippet}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
