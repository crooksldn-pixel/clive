// Base44 function host glue. Only the generated entry files import this;
// handlers stay runnable in tests without Deno or the SDK.
import { createClientFromRequest } from "npm:@base44/sdk@0.8.49";
import type { Base44Like, Deps } from "./types.ts";

declare const Deno: {
  serve(handler: (req: Request) => Response | Promise<Response>): unknown;
  env: { get(name: string): string | undefined };
};

/**
 * Secrets come from the newer host bridge when it exists, else from the
 * environment (the older Deno host, and `base44 dev`).
 */
export function readSecret(name: string): string | undefined {
  try {
    const bridge = (globalThis as { Base44?: { secrets?: { get(n: string): string | undefined } } }).Base44;
    const v = bridge?.secrets?.get(name);
    if (v) return v;
  } catch {
    // fall back to the environment
  }
  try {
    return Deno.env.get(name);
  } catch {
    return undefined;
  }
}

export function serve(handler: (req: Request, deps: Deps) => Promise<Response>) {
  Deno.serve(async (req: Request) => {
    let base44: Base44Like;
    try {
      base44 = createClientFromRequest(req) as unknown as Base44Like;
    } catch (e) {
      return Response.json({ ok: false, error: `Not called through Base44: ${(e as Error).message}` }, { status: 400 });
    }
    return handler(req, {
      base44,
      secret: readSecret,
      fetch: (input, init) => fetch(input, init),
      now: () => new Date(),
      sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
      appId: req.headers.get("Base44-App-Id"),
    });
  });
}
