import { FormEvent, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { App } from "./App";
import { authClient, authConfigurationError, localMode } from "./auth";
import { clearAccessToken, setAccessToken } from "./token";

export function AuthGate() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(localMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (localMode || !authClient) return;
    const client = authClient;
    let active = true;
    const { data: { subscription } } = client.auth.onAuthStateChange((_event, current) => {
      if (!active) return;
      setAccessToken(current?.access_token ?? null);
      setSession(current);
      setReady(true);
    });
    client.auth.getSession().then(({ data, error: issue }) => {
      if (!active) return;
      if (issue) setError("Impossible de vérifier la session.");
      setAccessToken(data.session?.access_token ?? null);
      setSession(data.session);
      setReady(true);
    }).catch(() => {
      if (active) {
        clearAccessToken();
        setSession(null);
        setError("Impossible de vérifier la session.");
        setReady(true);
      }
    });
    return () => {
      active = false;
      subscription.unsubscribe();
      clearAccessToken();
    };
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!authClient) return;
    setWorking(true);
    setError("");
    try {
      const { error: issue } = await authClient.auth.signInWithPassword({ email, password });
      if (issue) throw issue;
      setPassword("");
    } catch {
      setError("Connexion refusée. Vérifiez vos identifiants.");
      setPassword("");
    } finally {
      setWorking(false);
    }
  }

  async function signOut() {
    if (!authClient) return;
    setWorking(true);
    setError("");
    // Remove the bearer immediately, before the network logout resolves.
    clearAccessToken();
    setSession(null);
    try {
      const { error: issue } = await authClient.auth.signOut();
      if (issue) throw issue;
    } catch {
      setError("Déconnexion distante indisponible; accès local interrompu.");
    } finally {
      setWorking(false);
    }
  }

  if (localMode) return <App />;
  if (authConfigurationError) return <main className="shell"><p role="alert" className="error">{authConfigurationError}</p></main>;
  if (!ready) return <main className="shell"><p>Vérification de la session…</p></main>;
  if (session) return (
    <>
      <header className="authBar">
        <span>Connecté à TaskPlanner</span>
        <button type="button" disabled={working} onClick={() => void signOut()}>Se déconnecter</button>
      </header>
      <App />
    </>
  );
  return (
    <main className="shell">
      <section className="inbox authPanel">
        <p className="eyebrow">TaskPlanner</p>
        <h1>Connexion</h1>
        <p>Accès réservé au compte autorisé.</p>
        <form onSubmit={(event) => void signIn(event)}>
          <label>Adresse courriel<input type="email" autoComplete="username" required
            value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Mot de passe<input type="password" autoComplete="current-password" required
            value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button type="submit" disabled={working}>Se connecter</button>
        </form>
        {error && <p role="alert" className="error">{error}</p>}
      </section>
    </main>
  );
}
