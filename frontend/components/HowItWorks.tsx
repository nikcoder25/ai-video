import { CropIcon, SparkIcon, WaveIcon } from "./Icons";

const STEPS = [
  {
    n: "01",
    title: "Drop the long cut",
    body: "A YouTube link or a raw file. We pull the video and a clean 16 kHz audio track, then transcribe it down to the word.",
    Icon: WaveIcon,
  },
  {
    n: "02",
    title: "Find the moments",
    body: "Every candidate is scored on how hard it hooks in the first two seconds. Cuts land on sentence boundaries, never mid-word.",
    Icon: SparkIcon,
  },
  {
    n: "03",
    title: "Ship them vertical",
    body: "Reframed to 9:16 with the speaker centered and the crop path smoothed, captions burned in, loudness normalised.",
    Icon: CropIcon,
  },
];

export function HowItWorks() {
  return (
    <section aria-labelledby="how-it-works" className="w-full">
      <div className="rule mb-12" />
      <h2 id="how-it-works" className="eyebrow mb-8 text-fg-faint">
        How it works
      </h2>
      <div className="grid gap-x-10 gap-y-9 sm:grid-cols-3">
        {STEPS.map(({ n, title, body, Icon }) => (
          <div key={n} className="group relative">
            <div className="mb-4 flex items-center gap-3">
              <span className="numeric text-xs text-flame/70">{n}</span>
              <span className="h-px flex-1 bg-line" />
              <Icon className="h-4 w-4 text-fg-faint transition-colors duration-300 group-hover:text-flame" />
            </div>
            <h3 className="mb-2 text-[0.975rem] font-semibold tracking-tight text-fg">{title}</h3>
            <p className="text-sm leading-relaxed text-fg-muted">{body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
