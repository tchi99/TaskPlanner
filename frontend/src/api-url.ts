/** Resolve only TaskPlanner paths against a trusted API origin. Never forward bearer tokens to caller-supplied hosts. */
export function validApiOrigin(origin: string | undefined, production: boolean): boolean {
  if (!origin) return !production;
  try {
    const parsed = new URL(origin);
    return parsed.origin === origin &&
      (parsed.protocol === "https:" || (!production && parsed.protocol === "http:")) &&
      parsed.username === "" && parsed.password === "" &&
      parsed.pathname === "/" && parsed.search === "" && parsed.hash === "";
  } catch {
    return false;
  }
}

export function resolveApiUrl(path: string, origin: string | undefined, production: boolean): string {
  if (!(path === "/api" || path.startsWith("/api/")) || path.includes("\\") || /\s/.test(path)) {
    throw new Error("API destination not permitted");
  }
  const normalized = new URL(path, "https://taskplanner.invalid");
  if (!(normalized.pathname === "/api" || normalized.pathname.startsWith("/api/"))) {
    throw new Error("API destination not permitted");
  }
  if (!validApiOrigin(origin, production)) {
    throw new Error("Configuration de l'API invalide ou absente.");
  }
  return origin ? new URL(path, origin).href : path;
}
