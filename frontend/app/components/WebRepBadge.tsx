type Props = {
  score: number | null;
  cached: boolean | null;
  loading?: boolean;
};

function classify(score: number | null) {
  if (score == null) return { color: "bg-gray-200 text-gray-700", label: "—" };
  if (score < 30) return { color: "bg-red-200 text-red-900", label: String(score) };
  if (score <= 70) return { color: "bg-yellow-200 text-yellow-900", label: String(score) };
  return { color: "bg-green-200 text-green-900", label: String(score) };
}

export function WebRepBadge({ score, cached, loading }: Props) {
  if (loading) return <span className="text-xs text-blue-600">🌐 Live web lookup…</span>;
  const { color, label } = classify(score);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold ${color}`}
    >
      {label}
      {cached ? (
        <span title="cached" className="opacity-60">
          ·c
        </span>
      ) : null}
    </span>
  );
}
