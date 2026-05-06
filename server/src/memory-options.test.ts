import { describe, expect, test } from "bun:test";

import { buildMemoryOptions } from "./memory-options";

const observerModel = { role: "observer" } as never;
const reflectorModel = { role: "reflector" } as never;
const baseArgs = {
  observerModel,
  reflectorModel,
  shareBudget: false,
  temporal: true,
};

describe("memory option builder", () => {
  test("assigns large explicit output budgets to observer and reflector", () => {
    const options = buildMemoryOptions(baseArgs) as any;
    const om = options.observationalMemory;

    expect(om.observation.model).toBe(observerModel);
    expect(om.reflection.model).toBe(reflectorModel);
    expect(options.workingMemory).toEqual({
      enabled: true,
      scope: "resource",
      template: expect.stringContaining("# Hermes Working Memory"),
    });
    expect(options.lastMessages).toBe(20);
    expect(options.semanticRecall).toEqual({
      topK: 5,
      messageRange: { before: 2, after: 2 },
      scope: "resource",
      threshold: 0.65,
    });
    expect(options.filterIncompleteToolCalls).toBe(true);
    expect(options).not.toHaveProperty("processors");
    expect(om.enabled).toBe(true);
    expect(om.retrieval).toEqual({ vector: true, scope: "resource" });
    expect(om.activateAfterIdle).toBe("5m");
    expect(om.activateOnProviderChange).toBe(true);
    expect(om.observation.messageTokens).toBe(60_000);
    expect(om.observation.maxTokensPerBatch).toBe(40_000);
    expect(om.observation.bufferTokens).toBe(0.2);
    expect(om.observation.bufferActivation).toBe(0.8);
    expect(om.observation.blockAfter).toBe(1.2);
    expect(om.observation.previousObserverTokens).toBe(10_000);
    expect(om.observation.threadTitle).toBe(true);
    expect(om.observation.modelSettings.maxOutputTokens).toBe(100_000);
    expect(om.reflection.observationTokens).toBe(80_000);
    expect(om.reflection.bufferActivation).toBe(0.5);
    expect(om.reflection.blockAfter).toBe(1.2);
    expect(om.reflection.modelSettings.maxOutputTokens).toBe(100_000);
  });

  test("allows env payload to override observer and reflector output budgets", () => {
    const options = buildMemoryOptions({
      ...baseArgs,
      optionsJson: JSON.stringify({
        observationalMemory: {
          observation: { modelSettings: { maxOutputTokens: 64_000 } },
          reflection: { modelSettings: { maxOutputTokens: 96_000 } },
        },
      }),
    }) as any;
    const om = options.observationalMemory;

    expect(om.observation.model).toBe(observerModel);
    expect(om.reflection.model).toBe(reflectorModel);
    expect(om.observation.modelSettings.maxOutputTokens).toBe(64_000);
    expect(om.reflection.modelSettings.maxOutputTokens).toBe(96_000);
  });
});
