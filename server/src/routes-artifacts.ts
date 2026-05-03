/** Artifact routes — SOUL/MEMORY/USER/AGENTS.md as versioned prompt-blocks. */

import { Hono } from "hono";
import { ARTIFACT_KINDS } from "./config";
import {
  getArtifactBlock,
  revertArtifactBlock,
  upsertArtifactBlock,
  validateRevertBody,
} from "./helpers";

const app = new Hono();

app.get("/api/memory/artifact", async (c) => {
  const kind = (c.req.query("kind") ?? "").toLowerCase();
  const profile = c.req.query("profile") ?? "default";
  if (!ARTIFACT_KINDS.has(kind)) return c.json({ error: "invalid kind" }, 400);
  try {
    return c.json(await getArtifactBlock(kind, profile));
  } catch (err: any) {
    return c.json({ error: String(err?.message ?? err) }, 500);
  }
});

app.post("/api/memory/artifact", async (c) => {
  const body = (await c.req.json()) as {
    kind: string;
    profile?: string;
    content: string;
    path?: string;
    changeMessage?: string;
  };
  const kind = (body.kind ?? "").toLowerCase();
  const profile = body.profile ?? "default";
  if (!ARTIFACT_KINDS.has(kind)) return c.json({ error: "invalid kind" }, 400);
  if (typeof body.content !== "string") return c.json({ error: "content required" }, 400);
  try {
    return c.json(
      await upsertArtifactBlock(kind, profile, body.content, body.path, body.changeMessage),
    );
  } catch (err: any) {
    return c.json({ error: String(err?.message ?? err) }, 500);
  }
});

app.get("/api/memory/artifact/history", async (c) => {
  const kind = (c.req.query("kind") ?? "").toLowerCase();
  const profile = c.req.query("profile") ?? "default";
  const perPage = Math.max(1, Math.min(Number(c.req.query("per_page") ?? 20), 50));
  if (!ARTIFACT_KINDS.has(kind)) return c.json({ error: "invalid kind" }, 400);
  try {
    const { promptBlocksStore } = await import("./resources");
    const { artifactId } = await import("./config");
    const blocks = await promptBlocksStore();
    const id = artifactId(kind, profile);
    const out = await blocks.listVersions({
      blockId: id,
      perPage,
      orderBy: "versionNumber",
      direction: "DESC",
    });
    const versions = (out as any).versions ?? (out as any).items ?? [];
    return c.json({
      kind,
      profile,
      versions: versions.map((v: any) => ({
        version: v.versionNumber,
        created_at: v.createdAt,
        change_message: v.changeMessage ?? null,
        content: typeof v.content === "string" ? v.content : "",
      })),
    });
  } catch (err: any) {
    return c.json({ error: String(err?.message ?? err) }, 500);
  }
});

app.post("/api/memory/artifact/revert", async (c) => {
  const parsed = validateRevertBody(await c.req.json());
  if ("error" in parsed) return c.json(parsed, 400);
  try {
    return c.json(await revertArtifactBlock(parsed.kind, parsed.profile, parsed.version));
  } catch (err: any) {
    if (err.message?.includes("not found")) return c.json({ error: err.message }, 404);
    return c.json({ error: String(err?.message ?? err) }, 500);
  }
});

export default app;
