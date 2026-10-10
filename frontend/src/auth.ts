import { createClient } from "@supabase/supabase-js";
import { getAccessToken } from "./token";

// Deliberate local-only bypass: Vite production builds always require Supabase.
export const localMode = import.meta.env.DEV &&
  import.meta.env.VITE_TASKPLANNER_AUTH_MODE === "local";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
export const authConfigurationError = localMode || (supabaseUrl && publishableKey)
  ? null
  : "Configuration Supabase Auth absente. Contactez l'administrateur.";

export const authClient = !localMode && !authConfigurationError
  ? createClient(supabaseUrl, publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;

/** All business reads AND mutations must carry the short-lived Supabase access token. */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
  if (!(path === "/api" || path.startsWith("/api/"))) {
    throw new Error("API destination not permitted");
  }
  if (localMode) return fetch(input, init);
  const token = getAccessToken();
  if (!token) throw new Error("Session expirée. Veuillez vous reconnecter.");
  const headers = new Headers(init?.headers);
  headers.set("Authorization", "Bearer " + token);
  return fetch(input, { ...init, headers });
}
