import { LogoMark } from "./Icons";

export function SiteHeader({ onReset }: { onReset?: () => void }) {
  return (
    <header className="border-b border-line-soft">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
        <button
          type="button"
          onClick={onReset}
          className="group flex items-center gap-2.5 rounded-lg text-left"
          aria-label="ClipViral — start over"
        >
          <LogoMark className="h-7 w-7 transition-transform duration-300 group-hover:scale-105" />
          <span className="text-[0.95rem] font-semibold tracking-tight">
            Clip<span className="text-flame">Viral</span>
          </span>
        </button>

        <div className="flex items-center gap-2 text-fg-faint">
          <span className="hidden text-xs sm:block">Long video in, vertical clips out</span>
          <span className="hidden h-3 w-px bg-line sm:block" />
          <span className="numeric text-xs">9:16</span>
        </div>
      </div>
    </header>
  );
}
