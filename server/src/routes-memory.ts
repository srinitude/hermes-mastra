/** Core memory routes — health, messages, recall, working memory, observation, flush. */

import { Hono } from "hono";
import { DB_URL, RECALL_TOP_K, resourceFor, STARTED_AT } from "./config";
import { collectThreadObservations, mkMessage } from "./helpers";
import { ensureThread, memory, profilesSeen } from "./resources";

const app = new Hono();

app.get("/health", (c) =>
  c.json({
    ok: true,
    version: "0.2.2",
    profiles_seen: [...profilesSeen],
    pid: process.pid,
  }),
);

app.get("/api/memory/healthz", (c) =>
  c.json({
    ok: true,
    pid: process.pid,
    started_at: STARTED_AT,
    db: DB_URL ? "configured" : "missing",
    profile_count: profilesSeen.size,
  }),
);

app.post("/api/memory/messages", async (c) => {
  const body = await c.req.json();
  const { thread, profile, user, assistant, system } = body as {
    thread: string;
    profile?: string;
    user?: string;
    assistant?: string;
    system?: string;
  };
  if (!thread) return c.json({ error: "thread required" }, 400);
  const resource = resourceFor(profile ?? "default");
  profilesSeen.add(profile ?? "default");
  await ensureThread(thread, resource);

  const messages: ReturnType<typeof mkMessage>[] = [];
  if (system) messages.push(mkMessage("system", system, thread, resource, 0));
  if (user) messages.push(mkMessage("user", user, thread, resource, 1));
  if (assistant) messages.push(mkMessage("assistant", assistant, thread, resource, 2));
  if (!messages.length) return c.json({ saved: 0 });

  await memory.saveMessages({
    messages: messages as any,
    memoryConfig: { observationalMemory: true },
  });
  return c.json({ saved: messages.length, thread, resource });
});

app.get("/api/memory/recall", async (c) => {
  const thread = c.req.query("thread");
  const profile = c.req.query("profile") ?? "default";
  const limit = Number(c.req.query("limit") ?? RECALL_TOP_K);
  if (!thread) return c.json({ error: "thread required" }, 400);
  const resource = resourceFor(profile);
  const observations = (await collectThreadObservations(thread, resource)).slice(-limit);
  const text = observations
    .map((o: { text: string }, i: number) => `- [${i + 1}] ${o.text}`)
    .join("\n");
  return c.json({ thread, resource, count: observations.length, text });
});

async function _existingWorkingMemory(resource: string): Promise<string> {
  try {
    const wm = (await memory.getWorkingMemory({ resourceId: resource } as any)) as
      | string
      | { text?: string; content?: string }
      | null
      | undefined;
    return typeof wm === "string" ? wm : (wm?.text ?? wm?.content ?? "");
  } catch {
    return "";
  }
}

app.post("/api/memory/working_memory", async (c) => {
  const { profile, thread, content, action } = (await c.req.json()) as {
    profile?: string;
    thread?: string;
    content: string;
    action?: "set" | "append";
  };
  const resource = resourceFor(profile ?? "default");
  if (thread) await ensureThread(thread, resource);
  const existing = action === "append" ? await _existingWorkingMemory(resource) : "";
  const final = action === "append" && existing ? `${existing}\n${content}` : content;
  await memory.updateWorkingMemory({
    threadId: thread ?? `wm-${resource}`,
    resourceId: resource,
    workingMemory: final,
    memoryConfig: { workingMemory: { enabled: true, scope: "resource" } },
  } as any);
  return c.json({ ok: true, action: action ?? "set" });
});

app.get("/api/memory/working_memory", async (c) => {
  const profile = c.req.query("profile") ?? "default";
  const resource = resourceFor(profile);
  try {
    const wm = (await memory.getWorkingMemory({ resourceId: resource } as any)) as
      | string
      | { text?: string; content?: string }
      | null
      | undefined;
    return c.json({
      profile,
      resource,
      working_memory: typeof wm === "string" ? wm : (wm?.text ?? wm?.content ?? ""),
    });
  } catch {
    return c.json({ profile, resource, working_memory: "" });
  }
});

app.get("/api/memory/semantic_search", async (c) => {
  const query = (c.req.query("query") ?? "").trim();
  const profile = c.req.query("profile") ?? "default";
  const limit = Math.max(1, Math.min(Number(c.req.query("limit") ?? 8), 20));
  if (!query) return c.json({ error: "query required" }, 400);
  const resource = resourceFor(profile);
  try {
    const { results } = await memory.searchMessages({ query, resourceId: resource, topK: limit });
    const observations = results.map((r: any) => ({
      thread: r.threadId,
      text: r.text ?? "",
      score: r.score ?? null,
    }));
    return c.json({ resource, query, count: observations.length, observations });
  } catch {
    return c.json({ resource, query, count: 0, observations: [], fallback: "keyword" }, 200);
  }
});

async function _indexObs(text: string, thread: string, resource: string, ts: number) {
  await memory
    .indexObservation({
      text,
      groupId: `${thread}-${ts}-${Math.floor(Math.random() * 1e9).toString(36)}`,
      range: "manual",
      threadId: thread,
      resourceId: resource,
      observedAt: new Date(ts),
    })
    .catch(() => null);
}

app.post("/api/memory/observation", async (c) => {
  const body = (await c.req.json()) as {
    thread: string;
    profile?: string;
    text: string;
    kind?: string;
  };
  const { thread, profile, text, kind } = body;
  if (!thread || !text) return c.json({ error: "thread + text required" }, 400);
  const resource = resourceFor(profile ?? "default");
  await ensureThread(thread, resource);
  const tag = kind ? `[OBSERVATION:${kind}] ` : "[OBSERVATION] ";
  const fullText = `${tag}${text}`;
  const ts = Date.now();
  await memory.saveMessages({
    messages: [mkMessage("assistant", fullText, thread, resource, 0)] as any,
    memoryConfig: { observationalMemory: true },
  });
  await _indexObs(fullText, thread, resource, ts);
  return c.json({ ok: true });
});

app.post("/api/memory/flush", async (c) => {
  const { thread, profile } = (await c.req.json().catch(() => ({}))) as {
    thread?: string;
    profile?: string;
  };
  if (thread) {
    const resource = resourceFor(profile ?? "default");
    await memory
      .recall({
        threadId: thread,
        resourceId: resource,
        threadConfig: { observationalMemory: true },
      } as any)
      .catch(() => null);
  }
  return c.json({ ok: true });
});

export default app;
