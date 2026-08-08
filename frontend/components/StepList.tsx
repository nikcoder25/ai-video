import { PIPELINE_STEPS, type StepState } from "@/lib/stages";
import { AlertIcon, CheckIcon } from "./Icons";

export function StepList({ states }: { states: StepState[] }) {
  return (
    <ol className="relative">
      {PIPELINE_STEPS.map((step, index) => {
        const state: StepState = states[index] ?? "pending";
        const isLast = index === PIPELINE_STEPS.length - 1;

        return (
          <li
            key={step.stage}
            className="anim-step relative flex gap-4 pb-7 last:pb-0"
            style={{ animationDelay: `${index * 70}ms` }}
          >
            {/* connector */}
            {!isLast ? (
              <span
                aria-hidden="true"
                className={`absolute top-8 bottom-0 left-[13px] w-px transition-colors duration-500 ${
                  state === "complete" ? "bg-flame/40" : "bg-line"
                }`}
              />
            ) : null}

            <StepMarker state={state} />

            <div className="min-w-0 flex-1 pt-1">
              <div className="flex items-baseline gap-2.5">
                <h3
                  className={`text-[0.95rem] font-medium transition-colors duration-300 ${
                    state === "active"
                      ? "text-fg"
                      : state === "complete"
                        ? "text-fg-muted"
                        : state === "failed"
                          ? "text-danger"
                          : "text-fg-faint"
                  }`}
                >
                  {step.label}
                </h3>
                {state === "active" ? (
                  <span className="eyebrow text-flame">
                    <span className="anim-blink">running</span>
                  </span>
                ) : null}
                {state === "failed" ? <span className="eyebrow text-danger">failed</span> : null}
              </div>

              <p
                className={`mt-1 text-sm leading-relaxed transition-colors duration-300 ${
                  state === "pending" ? "text-fg-faint/60" : "text-fg-muted"
                }`}
              >
                {step.detail}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function StepMarker({ state }: { state: StepState }) {
  if (state === "complete") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-flame/45 bg-flame/12 text-flame">
        <CheckIcon className="h-3.5 w-3.5" />
      </span>
    );
  }

  if (state === "failed") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-danger/50 bg-danger/12 text-danger">
        <AlertIcon className="h-3.5 w-3.5" />
      </span>
    );
  }

  if (state === "active") {
    return (
      <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-flame bg-canvas">
        <span className="anim-halo absolute inset-0 rounded-full bg-flame/30" />
        <span className="relative h-2 w-2 rounded-full bg-flame" />
      </span>
    );
  }

  return (
    <span className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line bg-canvas">
      <span className="h-1.5 w-1.5 rounded-full bg-line" />
    </span>
  );
}
