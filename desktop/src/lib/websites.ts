import { writable } from "svelte/store";
import { fetchWebsites, type WebsiteInfo, type TestTarget } from "./api";

export const websites = writable<WebsiteInfo[]>([]);
export const websiteCatalogState = writable<"loading" | "ready" | "error">("loading");
export const websiteCatalogError = writable("");
let ticket = 0;

export async function refreshWebsites(key: string) {
  const current = ++ticket;
  websiteCatalogState.set("loading");
  try {
    const items = await fetchWebsites(key);
    if (current !== ticket) return;
    websites.set(items);
    websiteCatalogError.set("");
    websiteCatalogState.set("ready");
  } catch (error) {
    if (current !== ticket) return;
    websiteCatalogError.set((error as Error).message);
    websiteCatalogState.set("error");
  }
}

export function belongsToWebsite(target: TestTarget, site: WebsiteInfo): boolean {
  const domain = (host: string) => host.toLowerCase().replace(/^www\./, "");
  return site.hosts.some((host) => domain(host) === domain(target.host));
}
