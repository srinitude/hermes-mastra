/** Server-wide configuration — env vars, model knobs, limits. */

export const PORT = Number(process.env.MASTRA_PORT ?? 4191);
export const HOST = process.env.MASTRA_HOST ?? "127.0.0.1";
export const DB_URL = process.env.MASTRA_DB_URL ?? "file:./mastra.db";
export const AUTH_TOKEN = process.env.MASTRA_API_KEY ?? "";

// Single-model legacy fallbacks (used only if observer/reflector are not split).
const MODEL_URL = process.env.MASTRA_MODEL_URL ?? "https://api.venice.ai/api/v1";
const _MODEL_NAME = process.env.MASTRA_MODEL_NAME ?? "gemini-3-flash-preview";
const MODEL_API_KEY = process.env.MASTRA_MODEL_API_KEY ?? process.env.VENICE_API_KEY ?? "";

// Split-model knobs.  Observer = the high-frequency summarizer, Reflector =
// the lower-frequency restructurer that benefits from a stronger model.
export const OBSERVER_URL = process.env.MASTRA_OBSERVER_URL ?? MODEL_URL;
export const OBSERVER_NAME = process.env.MASTRA_OBSERVER_NAME ?? "gemini-3-flash-preview";
export const OBSERVER_API_KEY =
  process.env.MASTRA_OBSERVER_API_KEY ?? process.env.VENICE_API_KEY ?? MODEL_API_KEY;

export const REFLECTOR_URL = process.env.MASTRA_REFLECTOR_URL ?? MODEL_URL;
export const REFLECTOR_NAME = process.env.MASTRA_REFLECTOR_NAME ?? "gemini-3-1-pro-preview";
export const REFLECTOR_API_KEY =
  process.env.MASTRA_REFLECTOR_API_KEY ?? process.env.VENICE_API_KEY ?? MODEL_API_KEY;

export const TEMPORAL = (process.env.MASTRA_TEMPORAL ?? "true") === "true";
export const SHARE_BUDGET = (process.env.MASTRA_SHARE_BUDGET ?? "false") === "true";
export const RECALL_TOP_K = Number(process.env.MASTRA_RECALL_TOP_K ?? 4);

export const EMBEDDER_MODEL = process.env.MASTRA_EMBEDDER_MODEL ?? "google/gemini-embedding-001";

export const ARTIFACT_KINDS = new Set(["soul", "memory", "user", "agents"]);
export const STARTED_AT = new Date().toISOString();

export const resourceFor = (profile: string) => `hermes:${profile || "default"}`;
export const isAuthed = (auth: string | undefined) =>
  !AUTH_TOKEN || auth === `Bearer ${AUTH_TOKEN}`;
export const artifactId = (kind: string, profile: string) =>
  `hermes:${kind}:${profile || "default"}`;
