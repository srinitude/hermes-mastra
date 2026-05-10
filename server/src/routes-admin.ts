/** Admin routes — resources, threads, observations, search, reset. */

import { Hono } from "hono";
import { resourceFor } from "./config";
import { collectThreadObservations, matchesIn, type ObsHit } from "./helpers";
import { memory, profilesSeen } from "./resources";

const app = new Hono();

app.get("/api/memory/resources", (c) => c.json({ resources: [...profilesSeen].map(resourceFor) }));

app.get("/api/memory/threads", async (c) => {
  const profile = c.req.query("profile") ?? "default";
  const resource = resourceFor(profile);
  const result = await memory
    .listThreads({ filter: { resourceId: resource } })
    .catch(() => ({ threads: [] }));
  const allThreads = (result as any).threads ?? [];
  const threads = allThreads.filter((t: any) => t.resourceId === resource);
  return c.json({ resource, threads });
});

app.get("/api/memory/observations", async (c) => {
  const thread = c.req.query("thread");
  const profile = c.req.query("profile") ?? "default";
  if (!thread) return c.json({ error: "thread required" }, 400);
  const resource = resourceFor(profile);
  const observations = await collectThreadObservations(thread, resource);
  return c.json({ thread, resource, observations });
});

app.get("/api/memory/search", async (c) => {
  const query = (c.req.query("query") ?? "").trim();
  const profile = c.req.query("profile") ?? "default";
  const limit = Math.max(1, Math.min(Number(c.req.query("limit") ?? 8), 20));
  if (!query) return c.json({ error: "query required" }, 400);
  const resource = resourceFor(profile);
  const needle = query.toLowerCase();

  const threadList = await memory
    .listThreads({ filter: { resourceId: resource } })
    .catch(() => ({ threads: [] as any[] }));
  const threads = ((threadList as any).threads ?? []).filter((t: any) => t.resourceId === resource);

  const matches: ObsHit[] = [];
  for (const t of threads) {
    if (matches.length >= limit) break;
    const obs = await collectThreadObservations((t as any).id, resource);
    matches.push(...matchesIn((t as any).id, obs, needle, limit - matches.length));
  }
  return c.json({ resource, query, count: matches.length, observations: matches });
});

app.post("/api/memory/reset", async (c) => {
  const { profile } = (await c.req.json()) as { profile: string };
  if (!profile) return c.json({ error: "profile required" }, 400);
  const resource = resourceFor(profile);
  const result = await memory
    .listThreads({ filter: { resourceId: resource } })
    .catch(() => ({ threads: [] as any[] }));
  const allThreads = (result as any).threads ?? [];
  const threads = allThreads.filter((t: any) => t.resourceId === resource);
  for (const t of threads) {
    try {
      await memory.deleteThread((t as any).id);
    } catch {
      /* ignore */
    }
  }
  profilesSeen.delete(profile);
  return c.json({ ok: true, deleted: threads.length });
});

export default app;
