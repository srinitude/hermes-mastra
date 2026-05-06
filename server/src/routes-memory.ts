/** Core memory routes — health, messages, recall, working memory, observation, flush. */

import { Hono } from "hono";
import { DB_URL, RECALL_TOP_K, resourceFor, STARTED_AT } from "./config";
import { mkMessage } from "./helpers";
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

  const result = await memory
    .recall({
      threadId: thread,
      resourceId: resource,
      threadConfig: { lastMessages: limit, semanticRecall: false, observationalMemory: true },
    } as any)
    .catch(() => ({ messages: [], observations: [] as any[] }));

  const observations = (result as any)?.observations ?? [];
  const text = observations
    .map((o: any, i: number) => `- [${i + 1}] ${o.text ?? o.content ?? ""}`)
    .join("\n");
  return c.json({ thread, resource, count: observations.length, text });
});

app.post("/api/memory/working_memory", async (c) => {
  const { profile, thread, content, action } = (await c.req.json()) as {
    profile?: string;
    thread?: string;
    content: string;
    action?: "set" | "append";
  };
  const resource = resourceFor(profile ?? "default");
  if (thread) await ensureThread(thread, resource);
  await memory.updateWorkingMemory({
    threadId: thread ?? `wm-${resource}`,
    resourceId: resource,
    workingMemory: content,
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

  const threadList = await memory
    .listThreads({ filter: { resourceId: resource } })
    .catch(() => ({ threads: [] as any[] }));
  const threads = ((threadList as any).threads ?? []).filter((t: any) => t.resourceId === resource);
  if (!threads.length) return c.json({ resource, query, count: 0, observations: [] });

  try {
    const result = await memory.recall({
      threadId: threads[0].id,
      resourceId: resource,
      vectorSearchString: query,
      threadConfig: { semanticRecall: { topK: limit } },
    } as any);
    const msgs = ((result as any).messages ?? []) as any[];
    const hits = msgs.slice(0, limit).map((m: any) => ({
      thread: m.threadId ?? threads[0].id,
      text: typeof m.content === "string" ? m.content : (m.content?.text ?? ""),
      score: m.score ?? null,
    }));
    return c.json({ resource, query, count: hits.length, observations: hits });
  } catch {
    return c.json({ resource, query, count: 0, observations: [], fallback: "keyword" }, 200);
  }
});

app.post("/api/memory/observation", async (c) => {
  const { thread, profile, text, kind } = (await c.req.json()) as {
    thread: string;
    profile?: string;
    text: string;
    kind?: string;
  };
  if (!thread || !text) return c.json({ error: "thread + text required" }, 400);
  const resource = resourceFor(profile ?? "default");
  await ensureThread(thread, resource);
  const tag = kind ? `[OBSERVATION:${kind}] ` : "[OBSERVATION] ";
  await memory.saveMessages({
    messages: [
      {
        id: `${thread}-${Date.now()}-obs`,
        role: "system",
        content: `${tag}${text}`,
        threadId: thread,
        resourceId: resource,
        createdAt: new Date(),
        format: 2,
      } as any,
    ],
    memoryConfig: { observationalMemory: true },
  });
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
