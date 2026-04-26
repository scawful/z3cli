import type { Z3cliClient } from "../ipc/client.js";
import { log } from "../output.js";

export interface ResolvedModel {
  alias: string;
  canonicalName: string;
  modelId: string;
  backend: string;
  apiBase: string;
}

interface ResolveResponse {
  alias?: unknown;
  canonical_name?: unknown;
  model_id?: unknown;
  backend?: unknown;
  api_base?: unknown;
}

/** Caches alias → runtime model id + endpoint so FIM hot path skips a per-call RPC. */
export class ModelResolver {
  private cache = new Map<string, ResolvedModel>();

  constructor(private client: Z3cliClient) {
    client.on("ready", () => this.cache.clear());
    client.on("route/select", () => this.cache.clear());
    client.on("event", (evt: { method?: string } | undefined) => {
      const m = evt?.method;
      if (m === "context/compacted" || m === "ready") return; // ready handled above
      if (typeof m === "string" && m.startsWith("route/")) this.cache.clear();
    });
  }

  async resolve(alias: string, autoLoad = false): Promise<ResolvedModel | null> {
    const key = alias.trim().toLowerCase();
    if (!key) return null;
    if (!autoLoad) {
      const cached = this.cache.get(key);
      if (cached) return cached;
    }
    try {
      const raw = await this.client.request<ResolveResponse>(
        "inventory/resolve",
        { alias, autoLoad },
        5_000,
      );
      const resolved: ResolvedModel = {
        alias: stringField(raw.alias, alias),
        canonicalName: stringField(raw.canonical_name, alias),
        modelId: stringField(raw.model_id, alias),
        backend: stringField(raw.backend, "studio"),
        apiBase: stringField(raw.api_base, ""),
      };
      if (!resolved.apiBase) {
        log(`inventory/resolve returned empty api_base for ${alias}`);
        return null;
      }
      this.cache.set(key, resolved);
      return resolved;
    } catch (err) {
      log(`inventory/resolve failed for ${alias}: ${(err as Error).message}`);
      return null;
    }
  }

  clear(): void {
    this.cache.clear();
  }
}

function stringField(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}
