import { createClient } from "@supabase/supabase-js";
import { getAccessToken } from "./token";
import { resolveApiUrl, validApiOrigin } from "./api-url";

// Deliberate local-only bypass: Vite production builds always require Supabase.
export const localMode = import.meta.env.DEV &&
  import.meta.env.VITE_TASKPLANNER_AUTH_MODE === "local";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
const apiOrigin = import.meta.env.VITE_TASKPLANNER_API_URL;
export const authConfigurationError = !localMode && (!supabaseUrl || !publishableKey)
  ? "Configuration Supabase Auth absente. Contactez l'administrateur."
  : !localMode && !validApiOrigin(apiOrigin, import.meta.env.PROD)
    ? "Configuration de l'API invalide ou absente. Contactez l'administrateur."
    : null;

export const authClient = !localMode && !authConfigurationError
  ? createClient(supabaseUrl, publishableKey, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    })
  : null;

/** All business reads AND mutations must carry the short-lived Supabase access token. */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  // Normalize even URL/Request inputs: never use an externally supplied host as a fetch destination.
  const path = typeof input === "string"
    ? input
    : input instanceof URL
      ? input.pathname + input.search
      : new URL(input.url).pathname + new URL(input.url).search;
  const destination = resolveApiUrl(path, apiOrigin, import.meta.env.PROD);
  const headers = new Headers(init?.headers);
  if (!localMode) {
    const token = getAccessToken();
    if (!token) throw new Error("Session expirée. Veuillez vous reconnecter.");
    headers.set("Authorization", "Bearer " + token);
  }
  try {
    return await fetch(destination, { ...init, headers });
  } catch {
    // Avoid leaking URLs, credentials or low-level network details to the UI.
    throw new Error("Connexion à l'API indisponible. Réessayez.");
  }
}
