import { percent } from "@/lib/format";

export function ProgressBar({
  value,
  active,
  tone = "flame",
}: {
  /** 0.0 - 1.0 */
  value: number;
  active: boolean;
  tone?: "flame" | "danger";
}) {
  const pct = percent(value);
  const barColor = tone === "danger" ? "bg-danger" : "bg-flame";

  return (
    <div>
      <div className="mb-2.5 flex items-baseline justify-between">
        <span className="eyebrow text-fg-faint">Overall progress</span>
        <span className="numeric text-2xl font-medium text-fg tabular-nums">
          {pct}
          <span className="text-base text-fg-faint">%</span>
        </span>
      </div>

      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Job progress"
        className="relative h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
      >
        <div
          className={`relative h-full rounded-full ${barColor} transition-[width] duration-700 ease-out`}
          style={{ width: `${Math.max(pct, 1.5)}%` }}
        >
          {active ? (
            <div className="absolute inset-0 overflow-hidden rounded-full">
              <div className="anim-sheen absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-white/45 to-transparent" />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
