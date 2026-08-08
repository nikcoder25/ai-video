import type { Job, JobStage } from "./api";

export interface PipelineStep {
  stage: Exclude<JobStage, "queued" | "failed" | "done">;
  label: string;
  detail: string;
}

/** Mirrors the backend pipeline order in `pipeline/run.py`. */
export const PIPELINE_STEPS: readonly PipelineStep[] = [
  { stage: "downloading", label: "Downloading", detail: "Pulling the source video and audio track" },
  { stage: "transcribing", label: "Transcribing", detail: "Word-level timestamps across the whole runtime" },
  { stage: "selecting", label: "Selecting", detail: "Scoring moments and picking the strongest hooks" },
  { stage: "rendering", label: "Rendering", detail: "Cutting, reframing to 9:16 and burning captions" },
  { stage: "uploading", label: "Uploading", detail: "Storing the finished clips" },
];

export type StepState = "pending" | "active" | "complete" | "failed";

/**
 * `stage: "failed"` doesn't say where it broke, so the caller passes the last
 * non-terminal stage it observed while polling.
 */
export function stepStates(job: Job | null, lastActiveStage: JobStage | null): StepState[] {
  if (!job) return PIPELINE_STEPS.map(() => "pending");

  if (job.stage === "done" || job.status === "done") {
    return PIPELINE_STEPS.map(() => "complete");
  }

  const failedAt =
    job.status === "failed" || job.stage === "failed" ? lastActiveStage : null;

  const reference = failedAt ?? job.stage;
  const index = PIPELINE_STEPS.findIndex((step) => step.stage === reference);

  return PIPELINE_STEPS.map((_, position) => {
    if (index === -1) return "pending"; // still queued
    if (position < index) return "complete";
    if (position > index) return "pending";
    return failedAt ? "failed" : "active";
  });
}

export function stageHeadline(job: Job | null): string {
  if (!job) return "Starting up";
  if (job.status === "failed" || job.stage === "failed") return "Something broke";
  switch (job.stage) {
    case "queued":
      return "Queued";
    case "downloading":
      return "Downloading the source";
    case "transcribing":
      return "Transcribing every word";
    case "selecting":
      return "Hunting for hooks";
    case "rendering":
      return "Rendering vertical cuts";
    case "uploading":
      return "Packing up your clips";
    case "done":
      return "Clips are ready";
    default:
      return "Working";
  }
}
