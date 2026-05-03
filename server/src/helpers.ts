/** Shared helpers — message construction, content extraction, artifact ops. */

import { ARTIFACT_KINDS, artifactId } from "./config";
import { memory, promptBlocksStore } from "./resources";

// ---------- message helpers ----------

export const mkMessage = (
  role: "user" | "assistant" | "system",
  text: string,
  thread: string,
  resource: string,
  idx: number,
) => ({
  id: `${thread}-${Date.now()}-${idx}`,
  role,
  content: {
    format: 2 as const,
    parts: [{ type: "text" as const, text }],
    content: text,
  },
  threadId: thread,
  resourceId: resource,
  createdAt: new Date(Date.now() + idx),
});

export const extractContent = (block: any): string => {
  if (!block) return "";
  if (typeof block.content === "string") return block.content;
  if (block.activeVersion?.content) return String(block.activeVersion.content);
  if (block.version?.content) return String(block.version.content);
  return "";
};

export const blockMetadata = (kind: string, profile: string, path?: string) => ({
  hermes: { kind, profile: profile || "default", path: path ?? null },
});

// ---------- search helpers ----------

export type ObsHit = { thread: string; text: string; kind: string | null };

export const obsTextOf = (o: any): string => (o?.text ?? o?.content ?? "").toString();

export async function collectThreadObservations(threadId: string, resource: string) {
  const result = await memory
    .recall({
      threadId,
      resourceId: resource,
      threadConfig: { lastMessages: 200, observationalMemory: true },
    } as any)
    .catch(() => ({ observations: [] as any[] }));
  return ((result as any).observations ?? []) as any[];
}

export function matchesIn(
  threadId: string,
  observations: any[],
  needle: string,
  room: number,
): ObsHit[] {
  const out: ObsHit[] = [];
  for (const o of observations) {
    if (out.length >= room) break;
    const text = obsTextOf(o);
    if (text.toLowerCase().includes(needle)) {
      out.push({ thread: threadId, text, kind: o.kind ?? null });
    }
  }
  return out;
}

// ---------- artifact helpers ----------

export async function getArtifactBlock(kind: string, profile: string) {
  const blocks = await promptBlocksStore();
  const id = artifactId(kind, profile);
  const block = await (blocks.getByIdResolved ? blocks.getByIdResolved(id) : blocks.getById(id));
  if (!block) return { kind, profile, content: "", exists: false };
  return {
    kind,
    profile,
    content: extractContent(block),
    version: block.activeVersionNumber ?? block.versionNumber ?? null,
    updated_at: block.updatedAt ?? null,
    exists: true,
  };
}

export async function upsertArtifactBlock(
  kind: string,
  profile: string,
  content: string,
  path: string | undefined,
  changeMessage: string | undefined,
) {
  const blocks = await promptBlocksStore();
  const id = artifactId(kind, profile);
  const existing = await blocks.getById(id);
  if (!existing) {
    await blocks.create({
      promptBlock: {
        id,
        authorId: "hermes-mastra",
        metadata: blockMetadata(kind, profile, path),
        content,
        changeMessage: changeMessage ?? "Initial seed from file",
      },
    });
  } else {
    await blocks.update({
      id,
      content,
      metadata: blockMetadata(kind, profile, path),
      changeMessage: changeMessage ?? "Updated by hermes-mastra",
    } as any);
  }
  return { ok: true as const, kind, profile, id };
}

export async function revertArtifactBlock(kind: string, profile: string, version: number) {
  const blocks = await promptBlocksStore();
  const id = artifactId(kind, profile);
  const out = await blocks.listVersions({
    blockId: id,
    perPage: 1000,
    orderBy: "versionNumber",
    direction: "ASC",
  });
  const versions = (out as any).versions ?? (out as any).items ?? [];
  const target = versions.find((v: any) => v.versionNumber === version);
  if (!target) throw new Error(`version ${version} not found`);
  await blocks.update({
    id,
    content: target.content,
    changeMessage: `Reverted to v${version}`,
  } as any);
  return { ok: true as const, kind, profile, reverted_to: version };
}

export function validateRevertBody(
  body: any,
): { kind: string; profile: string; version: number } | { error: string } {
  const kind = (body.kind ?? "").toLowerCase();
  const profile = body.profile ?? "default";
  const { version } = body;
  if (!ARTIFACT_KINDS.has(kind)) return { error: "invalid kind" };
  if (!Number.isInteger(version) || version < 1)
    return { error: "version (positive integer) required" };
  return { kind, profile, version };
}
