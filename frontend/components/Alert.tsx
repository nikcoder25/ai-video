import type { ReactNode } from "react";
import { AlertIcon } from "./Icons";

export function Alert({
  title,
  children,
  action,
}: {
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="anim-view flex items-start gap-3 rounded-xl border border-danger/35 bg-danger/8 px-4 py-3.5"
    >
      <AlertIcon className="mt-px h-[18px] w-[18px] shrink-0 text-danger" />
      <div className="min-w-0 flex-1 space-y-1">
        {title ? <p className="text-sm font-medium text-fg">{title}</p> : null}
        <p className="text-sm leading-relaxed text-fg-muted break-words">{children}</p>
        {action ? <div className="pt-1.5">{action}</div> : null}
      </div>
    </div>
  );
}
