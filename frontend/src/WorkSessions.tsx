import { apiFetch } from "./auth";
import { useEffect, useState } from "react";

type Session = {
  id: string;
  task_id: string;
  segment_id: string | null;
  status: "ACTIVE" | "PAUSED" | "FINISHED";
  revision: number;
  recorded_active_seconds: number;
  provisional_active_seconds: number;
  interruptions: number;
  planned_minutes: number | null;
  guardrail: string | null;
};
type Observation = {
  sessions: Session[];
  estimate_minutes: number | null;
  estimate_incomplete: boolean;
  observed_minutes: number;
  provisional_active_seconds: number;
  difference_minutes: number | null;
  has_open_sessions: boolean;
  coverage: string;
  disclaimer: string;
};
type Stats = {
  work_type_id: string | null;
  work_type_name: string;
  context: "TASK" | "SEGMENT";
  finished_sessions: number;
  median_session_minutes: number | null;
  interruption_frequency: number | null;
  completed_unit_samples: number;
  calibration_ready: boolean;
  median_estimated_minutes: number | null;
  median_observed_minutes: number | null;
  deviations_minutes: number[];
};
type Action = { action_type: string; target_id: string } | null;

async function request<T>(url: string, method = "GET", body?: object): Promise<T> {
  const response = await apiFetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "Opération impossible.");
  }
  return response.json() as Promise<T>;
}

function minutes(seconds: number): string {
  return (seconds / 60).toFixed(1);
}

/** Server owns every observation; no passive activity capture or browser timer. */
export function WorkSessions({ taskId, nextAction, suggestedMinutes }: {
  taskId: string;
  nextAction: Action;
  suggestedMinutes: number | null;
}) {
  const [observation, setObservation] = useState<Observation | null>(null);
  const [stats, setStats] = useState<Stats[]>([]);
  const [minutesPlanned, setMinutesPlanned] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function reload() {
    const [current, summary] = await Promise.all([
      request<Observation>(`/api/tasks/${taskId}/work-sessions`),
      request<Stats[]>("/api/work-sessions/stats"),
    ]);
    setObservation(current);
    setStats(summary);
  }
  useEffect(() => {
    let mounted = true;
    setObservation(null);
    setLoading(true);
    setError("");
    Promise.all([
      request<Observation>(`/api/tasks/${taskId}/work-sessions`),
      request<Stats[]>("/api/work-sessions/stats"),
    ]).then(([current, summary]) => {
      if (mounted) { setObservation(current); setStats(summary); }
    }).catch((err: unknown) => {
      if (mounted) setError(err instanceof Error ? err.message : "Chargement impossible.");
    }).finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [taskId]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      await request(`/api/tasks/${taskId}/work-sessions`, "POST", {
        segment_id: nextAction?.action_type === "WORK_ON_SEGMENT" ? nextAction.target_id : null,
        planned_minutes: minutesPlanned ? Number(minutesPlanned) : suggestedMinutes,
      });
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Démarrage impossible.");
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  async function transition(session: Session, action: "pause" | "resume" | "finish") {
    setBusy(true);
    setError("");
    try {
      await request(`/api/work-sessions/${session.id}/${action}`, "POST", {
        expected_revision: session.revision,
      });
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Modification impossible.");
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  const actionable = nextAction &&
    (nextAction.action_type === "WORK_ON_TASK" || nextAction.action_type === "WORK_ON_SEGMENT");
  const open = observation?.sessions.filter((entry) => entry.status !== "FINISHED") ?? [];

  return (
    <section className="segmentSummary" aria-label="Sessions de travail">
      <h4>Temps de travail observé</h4>
      <p className="muted">Le temps actif est compté seulement entre les actions explicites. En cas d'oubli d'arrêt, le temps affiché comme provisoire peut être surestimé.</p>
      {loading && <p className="muted">Chargement des sessions…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {!loading && !observation && <button type="button" onClick={() => {
        setLoading(true);
        void reload().catch((err: unknown) => setError(err instanceof Error ? err.message : "Chargement impossible."))
          .finally(() => setLoading(false));
      }}>Réessayer</button>}
      {observation && (
        <>
          <p><strong>Enregistré :</strong> {observation.observed_minutes} min.
            {observation.provisional_active_seconds > 0 &&
              <> · En cours, non confirmé : {minutes(observation.provisional_active_seconds)} min.</>}
          </p>
          <p><strong>Estimation :</strong> {observation.estimate_minutes === null ? "inconnue ou partielle" : `${observation.estimate_minutes} min`}.
            {observation.difference_minutes !== null &&
              <> · Écart observé : {observation.difference_minutes} min.</>}
          </p>
          <p className="muted">Couverture non vérifiée : les périodes non enregistrées restent inconnues, même après clôture.</p>
          {actionable && !observation.sessions.some((session) => session.status === "ACTIVE") && (
            <div className="segmentActions">
              <label>Bloc volontaire (min)
                <input type="number" min={1} max={1440} value={minutesPlanned}
                  placeholder={suggestedMinutes?.toString() ?? "Facultatif"}
                  onChange={(event) => setMinutesPlanned(event.target.value)} />
              </label>
              <button type="button" disabled={busy || (!!minutesPlanned && (Number(minutesPlanned) < 1 || Number(minutesPlanned) > 1440))}
                onClick={() => void start()}>Démarrer la prochaine action</button>
            </div>
          )}
          {open.length === 0 && <p className="muted">Aucune session ouverte ou interrompue.</p>}
          {open.map((session) => (
            <div key={session.id}>
              <p><strong>{session.status === "ACTIVE" ? "En cours" : "En pause"}</strong>
                {" · "}{minutes(session.recorded_active_seconds)} min confirmées
                {session.provisional_active_seconds > 0 &&
                  ` + ${minutes(session.provisional_active_seconds)} min provisoires`}.
                {" · "}{session.interruptions} interruption(s).
              </p>
              {session.guardrail && <p role="status">Le bloc volontaire est atteint. Pause ou réévaluation possible, sans obligation.</p>}
              <div className="segmentActions">
                {session.status === "ACTIVE" && (
                  <button type="button" disabled={busy} onClick={() => void transition(session, "pause")}>Interrompre</button>
                )}
                {session.status === "PAUSED" && (
                  <button type="button" disabled={busy} onClick={() => void transition(session, "resume")}>Reprendre</button>
                )}
                <button type="button" disabled={busy} onClick={() => void transition(session, "finish")}>Terminer la session</button>
              </div>
            </div>
          ))}
          {stats.length > 0 && (
            <details>
              <summary>Calibration descriptive par type de travail</summary>
              {stats.map((item) => (
                <p key={(item.work_type_id ?? "none") + item.context}>
                  {item.work_type_name} ({item.context === "TASK" ? "tâche" : "segment"}) : {item.finished_sessions} session(s),
                  durée médiane {item.median_session_minutes ?? "inconnue"} min,
                  interruptions {item.interruption_frequency === null ? "inconnues" : `${Math.round(100 * item.interruption_frequency)} %`}.
                  {item.calibration_ready
                    ? ` ${item.completed_unit_samples} unités estimées : médiane estimation ${item.median_estimated_minutes} min / observé ${item.median_observed_minutes} min.`
                    : ` ${item.completed_unit_samples}/3 unités admissibles : comparaison encore insuffisante.`}
                </p>
              ))}
              <p className="muted">Échantillons incomplets possibles. Aucune causalité ni modification automatique de tes estimations.</p>
            </details>
          )}
        </>
      )}
    </section>
  );
}
