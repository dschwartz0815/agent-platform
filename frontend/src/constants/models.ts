/**
 * Shared list of Anthropic models used by node property panels and the
 * Agent registration form. Keep this list in sync with what the backend
 * actually accepts — in practice, any model ID the Anthropic SDK knows
 * will work.
 */

export interface ModelOption {
  id: string;
  label: string;
}

export const ANTHROPIC_MODELS: ModelOption[] = [
  { id: "claude-opus-4-6",           label: "Claude Opus 4.6 (most capable)" },
  { id: "claude-sonnet-4-6",         label: "Claude Sonnet 4.6 (balanced)" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5 (fast)" },
  { id: "claude-3-5-sonnet-20241022",label: "claude-3-5-sonnet (legacy)" },
];

export const DEFAULT_MODEL_ID = "claude-sonnet-4-6";
