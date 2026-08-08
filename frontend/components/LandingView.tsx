"use client";

import type { Job } from "@/lib/api";
import { ClipStack } from "./ClipStack";
import { HowItWorks } from "./HowItWorks";
import { SourceComposer } from "./SourceComposer";

export function LandingView({ onCreated }: { onCreated: (job: Job) => void }) {
  return (
    <div className="anim-view">
      <section className="grid grid-cols-1 items-center gap-14 pt-14 pb-20 lg:grid-cols-12 lg:gap-8 lg:pt-24 lg:pb-28">
        <div className="lg:col-span-7">
          <p className="eyebrow mb-6 flex items-center gap-2.5 text-fg-faint">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-flame" />
            Clip finder for long-form video
          </p>

          <h1 className="display text-[2.375rem] text-fg sm:text-[3rem] lg:text-[3.25rem]">
            Your best 40 seconds
            <br />
            <span className="text-fg-faint">are buried in</span>
            <br />
            <span className="text-flame">an hour of tape.</span>
          </h1>

          <p className="mt-7 max-w-xl text-[1.05rem] leading-relaxed text-fg-muted">
            ClipViral watches the whole thing, finds the moments that actually hook, and cuts them
            into captioned 9:16 clips — reframed on the speaker, ready to post.
          </p>

          <div className="mt-9 max-w-xl">
            <SourceComposer onCreated={onCreated} />
          </div>

          <p className="mt-4 max-w-xl text-xs leading-relaxed text-fg-faint">
            20–58 second cuts, word-level captions, no sentence cut in half.
          </p>
        </div>

        <div className="hidden lg:col-span-5 lg:block">
          <ClipStack />
        </div>
      </section>

      <HowItWorks />
    </div>
  );
}
