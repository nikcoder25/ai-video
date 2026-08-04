/**
 * Hook score 1-10, colour-graded on a cold → blazing ramp so the strongest
 * clips read as hotter at a glance.
 */

interface Heat {
  color: string;
  ink: string;
  filled: boolean;
  glow: boolean;
  label: string;
}

export function heatFor(score: number): Heat {
  const value = Math.max(1, Math.min(10, Math.round(score)));
  if (value >= 9) {
    return {
      color: "var(--color-heat-blazing)",
      ink: "#1a0602",
      filled: true,
      glow: true,
      label: "Blazing hook",
    };
  }
  if (value >= 7) {
    return {
      color: "var(--color-heat-hot)",
      ink: "#1a0f00",
      filled: true,
      glow: false,
      label: "Strong hook",
    };
  }
  if (value >= 5) {
    return {
      color: "var(--color-heat-warm)",
      ink: "#140d00",
      filled: true,
      glow: false,
      label: "Decent hook",
    };
  }
  return {
    color: "var(--color-heat-cold)",
    ink: "var(--color-heat-cold)",
    filled: false,
    glow: false,
    label: "Soft hook",
  };
}

export function HookScoreBadge({ score }: { score: number }) {
  const heat = heatFor(score);
  const value = Math.max(1, Math.min(10, Math.round(score)));

  return (
    <div
      title={`${heat.label} — ${value}/10`}
      className="flex items-center gap-1 rounded-lg px-2 py-1 backdrop-blur-sm"
      style={{
        backgroundColor: heat.filled ? heat.color : "rgba(10,10,12,0.72)",
        color: heat.filled ? heat.ink : heat.color,
        border: heat.filled ? "none" : "1px solid rgba(255,255,255,0.14)",
        boxShadow: heat.glow ? `0 0 22px -2px ${heat.color}` : "none",
      }}
    >
      <span className="numeric text-sm leading-none font-bold">{value}</span>
      <span className="numeric text-[0.65rem] leading-none opacity-65">/10</span>
    </div>
  );
}

export function HookScoreMeter({ score }: { score: number }) {
  const heat = heatFor(score);
  const value = Math.max(1, Math.min(10, Math.round(score)));

  return (
    <div
      className="flex items-center gap-[3px]"
      role="img"
      aria-label={`Hook score ${value} out of 10`}
    >
      {Array.from({ length: 10 }, (_, index) => (
        <span
          key={index}
          className="h-2.5 w-[3px] rounded-full transition-colors duration-300"
          style={{
            backgroundColor: index < value ? heat.color : "var(--color-surface-3)",
            opacity: index < value ? 1 - index * 0.035 : 1,
          }}
        />
      ))}
    </div>
  );
}
