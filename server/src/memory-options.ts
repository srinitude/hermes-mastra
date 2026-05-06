type JsonObject = Record<string, unknown>;

type BuildMemoryOptionsArgs = {
  observerModel: unknown;
  reflectorModel: unknown;
  shareBudget: boolean;
  temporal: boolean;
  optionsJson?: string;
};

const OUTPUT_TOKENS = 100_000;
const WORKING_MEMORY_TEMPLATE = `# Hermes Working Memory

## Current User / Resource
- Stable preferences:
- Durable profile facts:
- Active constraints:

## Current Task State
- Goal:
- Important files, URLs, or IDs:
- Open questions:

## Update Rules
- Keep this concise and current.
- Preserve useful durable facts; remove stale task details when they stop mattering.`;

const SEMANTIC_RECALL = {
  topK: 5,
  messageRange: { before: 2, after: 2 },
  scope: "resource",
  threshold: 0.65,
};

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const deepMerge = (base: JsonObject, overlay: JsonObject): JsonObject => {
  const out: JsonObject = { ...base };
  for (const [key, value] of Object.entries(overlay)) {
    const existing = out[key];
    out[key] = isObject(existing) && isObject(value) ? deepMerge(existing, value) : value;
  }
  return out;
};

const parsedOptions = (payload: string | undefined): JsonObject => {
  if (!payload) return {};
  const parsed = JSON.parse(payload) as unknown;
  return isObject(parsed) ? parsed : {};
};

const observationOptions = (model: unknown, shareBudget: boolean): JsonObject => {
  const options: JsonObject = {
    model,
    messageTokens: 60_000,
    modelSettings: { temperature: 0.3, maxOutputTokens: OUTPUT_TOKENS },
    maxTokensPerBatch: 40_000,
    bufferTokens: 0.2,
    bufferActivation: 0.8,
    blockAfter: 1.2,
    previousObserverTokens: 10_000,
    threadTitle: true,
  };
  if (shareBudget) options.bufferTokens = false;
  return options;
};

const baseOptions = (args: BuildMemoryOptionsArgs): JsonObject => ({
  readOnly: false,
  workingMemory: { enabled: true, scope: "resource", template: WORKING_MEMORY_TEMPLATE },
  lastMessages: 20,
  semanticRecall: SEMANTIC_RECALL,
  filterIncompleteToolCalls: true,
  observationalMemory: {
    enabled: true,
    retrieval: { vector: true, scope: "resource" },
    activateAfterIdle: "5m",
    activateOnProviderChange: true,
    observation: observationOptions(args.observerModel, args.shareBudget),
    reflection: {
      model: args.reflectorModel,
      observationTokens: 80_000,
      modelSettings: { temperature: 0, maxOutputTokens: OUTPUT_TOKENS },
      bufferActivation: 0.5,
      blockAfter: 1.2,
    },
    scope: "thread",
    temporalMarkers: args.temporal,
    shareTokenBudget: args.shareBudget,
  },
  generateTitle: false,
});

export const buildMemoryOptions = (args: BuildMemoryOptionsArgs): JsonObject =>
  deepMerge(baseOptions(args), parsedOptions(args.optionsJson ?? process.env.MASTRA_OPTIONS_JSON));
