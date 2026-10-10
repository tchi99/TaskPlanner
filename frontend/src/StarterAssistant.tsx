import { apiFetch } from "./auth";
import { FormEvent, useEffect, useState } from "react";
import { WorkSessions } from "./WorkSessions";

type NextAction = {
  action_type: string;
  target_id: string;
  label: string;
};
type StartAssistance = {
  next_action: NextAction | null;
  starter_action: { text: string; commitment_minutes: number } | null;
  strategies: { code: string; label: string }[];
  resume_point: {
    text: string;
    action_type: string;
    target_id: string;
    updated_at: string;
  } | null;
  resume_revision: number;
};

const headers = { "Content-Type": "application/json" };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const message = await response.json().catch(() => null);
    throw new Error(
      typeof message?.detail === "string" ? message.detail : "L'opération a échoué."
    );
  }
  return response.json() as Promise<T>;
}

/** Suggestions are transient; only an explicit resume-note command is persisted. */
export function StarterAssistant({
  taskId, onCapture,
}: {
  taskId: string;
  onCapture: () => Promise<void>;
}) {
  const [snapshot, setSnapshot] = useState<StartAssistance | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showSuggestion, setShowSuggestion] = useState(false);
  const [resumeText, setResumeText] = useState("");
  const [idea, setIdea] = useState("");
  const [captureError, setCaptureError] = useState("");
  const [capturing, setCapturing] = useState(false);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError("");
    setShowSuggestion(false);
    setSnapshot(null);
    setResumeText("");
    request<StartAssistance>("/api/tasks/" + taskId + "/start-assistance")
      .then((value) => {
        if (mounted) {
          setSnapshot(value);
          setResumeText(value.resume_point?.text ?? "");
        }
      })
      .catch((err: unknown) => {
        if (mounted) setError(err instanceof Error ? err.message : "Chargement impossible.");
      })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [taskId]);

  async function refresh(reveal: boolean) {
    setBusy(true);
    setError("");
    try {
      const value = await request<StartAssistance>(
        "/api/tasks/" + taskId + "/start-assistance"
      );
      setSnapshot(value);
      setResumeText(value.resume_point?.text ?? "");
      if (reveal) setShowSuggestion(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Chargement impossible.");
    } finally {
      setBusy(false);
      setLoading(false);
    }
  }

  async function persist(text: string | null) {
    if (!snapshot?.next_action) return;
    setBusy(true);
    setError("");
    try {
      const updated = await request<StartAssistance>(
        "/api/tasks/" + taskId + "/start-assistance/resume-point",
        {
          method: "PUT",
          headers,
          body: JSON.stringify({
            text,
            action_type: snapshot.next_action.action_type,
            target_id: snapshot.next_action.target_id,
            expected_revision: snapshot.resume_revision,
            confirmed: true,
          }),
        },
      );
      setSnapshot(updated);
      setResumeText(updated.resume_point?.text ?? "");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function capture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!idea.trim()) return;
    setCapturing(true);
    setCaptureError("");
    try {
      await request("/api/tasks", {
        method: "POST",
        headers,
        body: JSON.stringify({ title: idea.trim() }),
      });
      setIdea("");
      await onCapture();
    } catch (err: unknown) {
      setCaptureError(err instanceof Error ? err.message : "Capture impossible.");
    } finally {
      setCapturing(false);
    }
  }

  return (
    <section className="starterPanel" aria-label="Amorçage et reprise">
      <h4>Amorçage et reprise</h4>
      {loading && <p className="muted">Chargement du point de reprise…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {!loading && !snapshot && (
        <button type="button" disabled={busy} onClick={() => void refresh(false)}>
          Réessayer
        </button>
      )}
      {snapshot && (
        <>
          <p><strong>Next Action :</strong> {snapshot.next_action?.label ?? "Aucune prochaine action ouverte."}</p>
          {snapshot.resume_point && (
            <p className="resumeMarker"><strong>Reprendre ici :</strong> {snapshot.resume_point.text}</p>
          )}
          {snapshot.next_action && (
            <>
              <button type="button" disabled={busy} onClick={() => void refresh(true)}>
                {busy ? "Préparation…" : "Aide-moi à commencer"}
              </button>
              {showSuggestion && snapshot.starter_action && (
                <div className="starterSuggestion" aria-live="polite">
                  <p><strong>Starter Action (suggestion) :</strong> {snapshot.starter_action.text}</p>
                  <p className="muted">
                    Engagement proposé : {snapshot.starter_action.commitment_minutes} minutes,
                    sans obligation de terminer. Aucun état de tâche n'est modifié.
                  </p>
                  <p><strong>Autres stratégies possibles</strong></p>
                  <ul>
                    {snapshot.strategies.map((strategy) => (
                      <li key={strategy.code}>{strategy.label}</li>
                    ))}
                  </ul>
                </div>
              )}
              <form className="segmentForm" onSubmit={(event) => {
                event.preventDefault();
                void persist(resumeText.trim());
              }}>
                <label>Point de reprise (max. 240 caractères)
                  <textarea maxLength={240} value={resumeText}
                    placeholder="Reprendre ici : vérifier le premier élément…"
                    onChange={(event) => setResumeText(event.target.value)} />
                </label>
                <div className="segmentActions">
                  <button type="submit" disabled={busy || !resumeText.trim()}>
                    Enregistrer le point de reprise
                  </button>
                  {snapshot.resume_point && (
                    <button type="button" disabled={busy} onClick={() => void persist(null)}>
                      Effacer le point de reprise
                    </button>
                  )}
                </div>
                <p className="muted">Enregistrement explicite, sans lancer de session ni modifier les priorités.</p>
              </form>
            </>
          )}
        </>
      )}
      {snapshot && <WorkSessions taskId={taskId} nextAction={snapshot.next_action}
        suggestedMinutes={showSuggestion ? snapshot.starter_action?.commitment_minutes ?? null : null} />}
      <form className="quickCapture" onSubmit={(event) => void capture(event)}>
        <label>Capturer une idée sans quitter ce travail
          <input maxLength={500} value={idea} placeholder="Nouvelle idée…"
            onChange={(event) => setIdea(event.target.value)} />
        </label>
        <button disabled={capturing || !idea.trim()} type="submit">
          {capturing ? "Capture…" : "Ajouter à l'Inbox"}
        </button>
        {captureError && <p role="alert" className="error">{captureError}</p>}
      </form>
    </section>
  );
}
