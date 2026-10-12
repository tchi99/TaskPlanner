import { apiFetch } from "./auth";
import { useEffect, useState } from "react";

type Block = {
  id?: string;
  task_id: string;
  segment_id: string | null;
  label?: string;
  starts_at: string;
  ends_at: string;
  minutes?: number;
  work_type_id?: string | null;
  status?: string;
  revision?: number;
};
type Unplaced = {
  task_id: string;
  label: string;
  remaining_minutes: number | null;
  reason: string;
};
type Preview = {
  state: "PROPOSED";
  fingerprint: string;
  can_confirm: boolean;
  calendar_checked: boolean;
  destinations: "TASKPLANNER_LOCAL_ONLY";
  suggestions: Block[];
  unplaced: Unplaced[];
};
type Cancellation = {
  block: Block;
  fingerprint: string;
  consequences: string[];
  payload: { decision: "CANCEL"; expected_revision: number; timezone_name: string; reason: string };
};
type Confirmation = {
  state: "CONFIRMED_LOCAL";
  calendar_written: false;
  blocks: Block[];
};

const headers = { "Content-Type": "application/json" };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(response.status === 409 ?
      "Réservation ou aperçu périmé (409). Actualise avant de recommencer." :
      typeof data?.detail === "string" ? data.detail : "Opération impossible.");
  }
  return response.json() as Promise<T>;
}

const description: Record<string, string> = {
  ESTIMATE_UNKNOWN: "Estimation inconnue : préciser l'effort avant confirmation.",
  ALREADY_CONFIRMED: "Des créneaux existent déjà pour cette tâche durant cette semaine.",
  INSUFFICIENT_FREE_TIME_BEFORE_DEADLINE:
    "Temps libre insuffisant pour placer toute la charge avant l'échéance.",
};

export function TimeBlockPlanner({
  weekStart, taskIds, taskNames = {}, workTypeNames = {}, onBookingChanged,
}: {
  weekStart: string;
  taskIds: string[];
  taskNames?: Record<string, string>;
  workTypeNames?: Record<string, string>;
  onBookingChanged?: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState<Block[]>([]);
  const [cancellation, setCancellation] = useState<Cancellation | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const base = `/api/capacity/weeks/${weekStart}/time-blocks`;
  const timezone_name = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  useEffect(() => {
    let active = true;
    request<Block[]>(base)
      .then((blocks) => { if (active) setConfirmed(blocks); })
      .catch(() => { if (active) setError("Impossible de lire les réservations locales."); });
    return () => { active = false; };
  }, [base]);

  async function propose() {
    setBusy(true);
    setPreview(null); setCancellation(null);
    setError(""); setMessage("");
    try {
      const result = await request<Preview>(base + "/preview", {
        method: "POST", headers,
        body: JSON.stringify({ task_ids: taskIds, timezone_name }),
      });
      setPreview(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Proposition impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview?.can_confirm) return;
    if (!window.confirm(
      "Confirmer l'enregistrement local de ces créneaux ? " +
      "Ils ne seront PAS créés dans Google Calendar."
    )) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request<Confirmation>(base + "/confirm", {
        method: "POST", headers,
        body: JSON.stringify({
          task_ids: taskIds,
          timezone_name,
          fingerprint: preview.fingerprint,
          confirmed: true,
        }),
      });
      setPreview(null);
      setMessage(`${result.blocks.length} créneau(x) confirmé(s) dans TaskPlanner seulement. Aucun événement Google créé.`);
      setConfirmed(await request<Block[]>(base));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "La proposition doit être recalculée.");
      setPreview(null); // Never allow a stale preview to be applied twice.
    } finally {
      setBusy(false);
    }
  }

  async function previewCancellation(block: Block) {
    if (busy || !block.id || block.status !== "CONFIRMED" || !block.revision) return;
    setBusy(true); setError(""); setMessage(""); setCancellation(null); setPreview(null);
    const payload = { decision: "CANCEL" as const, expected_revision: block.revision,
      timezone_name, reason: "Annulation manuelle" };
    try {
      const result = await request<{ fingerprint: string; consequences: string[] }>(
        `${base}/${block.id}/resolution/preview`, {
          method: "POST", headers, body: JSON.stringify(payload),
        });
      setCancellation({ block, fingerprint: result.fingerprint, consequences: result.consequences, payload });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Aperçu d’annulation impossible.");
    } finally { setBusy(false); }
  }

  async function confirmCancellation() {
    if (!cancellation || busy || !cancellation.block.id) return;
    if (!window.confirm("Annuler uniquement cette réservation locale ? La tâche reste inchangée et aucun événement Google n’est modifié.")) return;
    const draft = cancellation;
    setBusy(true); setError(""); setMessage("");
    try {
      await request(`${base}/${draft.block.id}/resolution/confirm`, {
        method: "POST", headers, body: JSON.stringify({ ...draft.payload,
          fingerprint: draft.fingerprint, decision_id: crypto.randomUUID(), confirmed: true }),
      });
      setCancellation(null); setPreview(null);
      setConfirmed(await request<Block[]>(base));
      onBookingChanged?.();
      setMessage("Réservation annulée localement. Tâche inchangée; capacité et propositions à recalculer selon les contraintes. Aucun événement Google modifié.");
    } catch (err: unknown) {
      setCancellation(null);
      setError(err instanceof Error ? err.message : "Annulation impossible.");
      try { setConfirmed(await request<Block[]>(base)); } catch { /* Conserver le diagnostic principal. */ }
    } finally { setBusy(false); }
  }

  const activeConfirmed = confirmed.filter((block) => block.id && block.status === "CONFIRMED");
  const describe = (block: Block) =>
    `${new Date(block.starts_at).toLocaleString()} – ${new Date(block.ends_at).toLocaleString()}`;

  return (
    <div className="capacityResult">
      <h3>TP-041 — Proposer des créneaux</h3>
      <p className="muted">Utilise seulement les plages disponibles saisies, moins les événements occupés
        de Google Calendar et les réservations locales. Google Calendar demeure en lecture seule.
        La confirmation enregistre dans TaskPlanner, jamais dans Google Calendar.</p>
      <button type="button" disabled={busy || taskIds.length === 0} onClick={() => void propose()}>
        {busy ? "Vérification…" : "Proposer des créneaux pour la sélection"}
      </button>
      {error && <p role="alert" className="error">{error} Les engagements doivent être relus avant confirmation.</p>}
      {message && <p role="status">{message}</p>}
      {preview && (
        <div aria-live="polite">
          <h4>Proposition non enregistrée</h4>
          {preview.suggestions.length === 0 ? (
            <p>Aucun créneau proposé.</p>
          ) : (
            <ul className="capacityBlocks">{preview.suggestions.map((block, index) => (
              <li key={index}><span>{block.label} · {describe(block)} · {block.minutes} min</span></li>
            ))}</ul>
          )}
          {preview.unplaced.length > 0 && (
            <div>
              <strong>Charge non placée — confirmation impossible</strong>
              <ul>{preview.unplaced.map((item, index) => (
                <li key={index}>{item.label} : {description[item.reason] ?? item.reason}
                  {item.remaining_minutes !== null && ` (${item.remaining_minutes} min)`}</li>
              ))}</ul>
            </div>
          )}
          <button type="button" disabled={busy || !preview.can_confirm}
            onClick={() => void confirm()}>Confirmer les créneaux locaux</button>
          {!preview.can_confirm && <p className="muted">Toute la charge doit être placée avant validation.</p>}
        </div>
      )}
      <h4>Créneaux déjà confirmés dans TaskPlanner</h4>
      {activeConfirmed.length === 0 ? <p className="muted">Aucune réservation locale active.</p> : (
        <ul className="capacityBlocks">{activeConfirmed.map((block) => (
          <li key={block.id}>
            <span>{describe(block)} · tâche {taskNames[block.task_id] || block.task_id.slice(0, 8)}
              {block.segment_id ? ` / segment ${block.segment_id.slice(0, 8)}` : ""}
              {" · "}{block.work_type_id ? workTypeNames[block.work_type_id] || block.work_type_id.slice(0, 8) : "Non classé"}
              {" · "}{block.status}</span>
            <button type="button" disabled={busy} aria-label={`Annuler la réservation ${block.id?.slice(0, 8)}`}
              onClick={() => void previewCancellation(block)}>Annuler la réservation</button>
          </li>
        ))}</ul>
      )}
      {cancellation && <div className="capacityResult" aria-live="polite">
        <h4>Aperçu d’annulation — réservation {cancellation.block.id?.slice(0, 8)}</h4>
        <p>{describe(cancellation.block)} · tâche {taskNames[cancellation.block.task_id] || cancellation.block.task_id.slice(0, 8)}.</p>
        <ul>{cancellation.consequences.map((item, index) => <li key={index}>{item}</li>)}</ul>
        <p>Seule cette réservation sera annulée. La tâche reste inchangée; les minutes pourront redevenir planifiables selon les autres contraintes. Aucun événement Google ne sera modifié.</p>
        <button type="button" disabled={busy} onClick={() => void confirmCancellation()}>Confirmer l’annulation locale</button>
        <button type="button" disabled={busy} onClick={() => setCancellation(null)}>Garder la réservation</button>
      </div>}
    </div>
  );
}
