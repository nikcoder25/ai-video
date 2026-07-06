import Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import { config } from "../config";
import { log } from "../logger";
import type { Product } from "./scrape";

export interface ScriptVariant {
  /** 1-second attention hook shown as a text card and spoken first. */
  hook: string;
  /** The full voiceover text (~12-18s spoken). */
  script: string;
}

const ScriptSetSchema = z.object({
  variants: z
    .array(
      z.object({
        hook: z.string(),
        script: z.string(),
      }),
    )
    .min(1),
});

// JSON Schema sent to the API. Structured outputs reject numeric/length
// constraints, so we keep it to types + required + additionalProperties:false.
const OUTPUT_SCHEMA = {
  type: "object",
  properties: {
    variants: {
      type: "array",
      items: {
        type: "object",
        properties: {
          hook: { type: "string", description: "Punchy 3-6 word hook spoken in the first second." },
          script: {
            type: "string",
            description: "First-person UGC voiceover, ~35-55 words, ending in a clear CTA.",
          },
        },
        required: ["hook", "script"],
        additionalProperties: false,
      },
    },
  },
  required: ["variants"],
  additionalProperties: false,
};

const SYSTEM = `You are an expert short-form UGC ad scriptwriter for TikTok/Reels dropshipping ads.
You write scripts that sound like a real person filmed on their phone, not a brand.
Rules:
- First person, conversational, high energy. No corporate language.
- The hook must create instant curiosity, tension, or a bold claim.
- One clear benefit per script, one CTA at the end ("link's right here", "grab yours before it sells out", etc).
- Keep each script to ~35-55 spoken words. No stage directions, no emojis, just the words to be spoken.
- Return exactly 3 variants that take genuinely different angles (problem/solution, before/after, social proof).`;

function buildUserPrompt(product: Product): string {
  return [
    `Product: ${product.title}`,
    product.price ? `Price: ${product.price}` : null,
    product.description ? `Details: ${product.description.slice(0, 600)}` : null,
    "",
    "Write 3 UGC ad scripts, each with a hook and a voiceover script.",
  ]
    .filter(Boolean)
    .join("\n");
}

function mockScripts(product: Product): ScriptVariant[] {
  const name = product.title.split(/[|\-–—]/)[0].trim() || "this";
  return [
    {
      hook: "Okay this is genius",
      script: `I did not expect ${name} to be this good. I've tried everything and nothing worked until this. It's honestly changed my whole routine and I'm never going back. Grab yours from the link before they sell out again.`,
    },
    {
      hook: "Stop scrolling for a sec",
      script: `If you deal with this every single day, you need to see ${name}. Two minutes to set up and the difference is insane. My friends keep asking where I got it. Link's right here, go get one.`,
    },
    {
      hook: "Why did no one tell me",
      script: `I wish I found ${name} sooner. It's the one thing that actually delivered on what it promised. Worth every rupee and then some. Tap the link and thank me later.`,
    },
  ];
}

/**
 * Generate 3 hook+script variants. Uses Claude with structured output, or
 * canned scripts when MOCK=1 / no API key.
 */
export async function generateScripts(product: Product): Promise<ScriptVariant[]> {
  log.step("Write scripts (Claude)");

  if (config.mock || !config.anthropicApiKey) {
    if (!config.mock) log.warn("no ANTHROPIC_API_KEY — using mock scripts");
    const variants = mockScripts(product);
    variants.forEach((v, i) => log.ok(`variant ${i + 1}: "${v.hook}"`));
    return variants;
  }

  const client = new Anthropic({ apiKey: config.anthropicApiKey });
  // Force a single tool call to get guaranteed-structured JSON (works on any
  // SDK version; output_config isn't typed until a later SDK release).
  const response = await client.messages.create({
    model: config.scriptModel,
    max_tokens: 4000,
    system: SYSTEM,
    messages: [{ role: "user", content: buildUserPrompt(product) }],
    tools: [
      {
        name: "emit_scripts",
        description: "Return the 3 UGC ad script variants.",
        input_schema: OUTPUT_SCHEMA as Anthropic.Tool.InputSchema,
      },
    ],
    tool_choice: { type: "tool", name: "emit_scripts" },
  });

  const toolBlock = response.content.find((b) => b.type === "tool_use");
  if (!toolBlock || toolBlock.type !== "tool_use") {
    throw new Error("Claude did not return the emit_scripts tool call");
  }
  const parsed = ScriptSetSchema.parse(toolBlock.input);
  const variants = parsed.variants.slice(0, 3);
  variants.forEach((v, i) => log.ok(`variant ${i + 1}: "${v.hook}"`));
  return variants;
}
