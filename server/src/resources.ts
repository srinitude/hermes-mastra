/** Shared Mastra resources — storage, memory, agents, profile tracking. */

import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { Agent } from "@mastra/core/agent";
import { LibSQLStore } from "@mastra/libsql";
import { Memory } from "@mastra/memory";
import {
  DB_URL,
  OBSERVER_API_KEY,
  OBSERVER_NAME,
  OBSERVER_URL,
  REFLECTOR_API_KEY,
  REFLECTOR_NAME,
  REFLECTOR_URL,
  SHARE_BUDGET,
  TEMPORAL,
} from "./config";

export const storage = new LibSQLStore({ id: "hermes-mastra", url: DB_URL });

const observerModel = createOpenAICompatible({
  name: "hermes-mastra-observer",
  baseURL: OBSERVER_URL,
  apiKey: OBSERVER_API_KEY,
})(OBSERVER_NAME);

const reflectorModel = createOpenAICompatible({
  name: "hermes-mastra-reflector",
  baseURL: REFLECTOR_URL,
  apiKey: REFLECTOR_API_KEY,
})(REFLECTOR_NAME);

const proxyModelName = process.env.MASTRA_PROXY_NAME ?? OBSERVER_NAME;
const proxyModel = createOpenAICompatible({
  name: "hermes-mastra-proxy",
  baseURL: OBSERVER_URL,
  apiKey: OBSERVER_API_KEY,
})(proxyModelName);

export const memory = new Memory({
  storage,
  options: {
    workingMemory: { enabled: true, scope: "resource" },
    lastMessages: 20,
    observationalMemory: {
      observation: {
        model: observerModel,
        ...(SHARE_BUDGET ? { bufferTokens: false } : {}),
      },
      reflection: { model: reflectorModel },
      scope: "thread",
      temporalMarkers: TEMPORAL,
      shareTokenBudget: SHARE_BUDGET,
    },
    generateTitle: false,
  },
});

export const _proxyAgent = new Agent({
  id: "hermes-mastra-proxy",
  name: "hermes-mastra-proxy",
  instructions: "You only summarize observations on demand. Do not invent facts.",
  model: proxyModel,
  memory,
});

export const profilesSeen = new Set<string>();

export const promptBlocksStore = async () => {
  const s = await (storage as any).getStore?.("promptBlocks");
  if (!s) throw new Error("prompt-blocks domain not available on this storage adapter");
  return s;
};

export const ensureThread = async (threadId: string, resource: string, title?: string) => {
  try {
    const existing = await memory.getThreadById({ threadId });
    if (existing) return existing;
  } catch {
    /* fall through */
  }
  return memory.createThread({
    threadId,
    resourceId: resource,
    title: title ?? `hermes-${threadId.slice(0, 12)}`,
  });
};
