/**
 * Hermes Mastra server — entry point.
 *
 * Composes Hono sub-apps from focused route modules, adds auth middleware,
 * and starts the Bun HTTP listener.  See individual route files for the
 * HTTP surface docs.
 */

import { Hono } from "hono";
import {
  AUTH_TOKEN,
  DB_URL,
  HOST,
  isAuthed,
  OBSERVER_NAME,
  OBSERVER_URL,
  PORT,
  REFLECTOR_NAME,
  REFLECTOR_URL,
  STARTED_AT,
} from "./config";
import routesAdmin from "./routes-admin";
import routesArtifacts from "./routes-artifacts";
import routesMemory from "./routes-memory";

const app = new Hono();

app.use("*", async (c, next) => {
  if (!isAuthed(c.req.header("authorization"))) return c.json({ error: "unauthorized" }, 401);
  await next();
});

app.route("/", routesMemory);
app.route("/", routesAdmin);
app.route("/", routesArtifacts);

console.log(
  JSON.stringify({
    msg: "hermes mastra server listening",
    host: HOST,
    port: PORT,
    db: DB_URL,
    observer: { url: OBSERVER_URL, name: OBSERVER_NAME },
    reflector: { url: REFLECTOR_URL, name: REFLECTOR_NAME },
    auth: AUTH_TOKEN ? "bearer" : "none",
    started_at: STARTED_AT,
  }),
);

Bun.serve({ port: PORT, hostname: HOST, fetch: app.fetch });
