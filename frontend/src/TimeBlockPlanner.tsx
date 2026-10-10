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
    throw new Error(typeof data?.detail === "string" ? data.detail : "Opération impossible.");
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
  weekStart, taskIds,
}: {
  weekStart: string;
  taskIds: string[];
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmed, setConfirmed] = useState<Block[]>([]);
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
    setPreview(null);
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
      {confirmed.length === 0 ? <p className="muted">Aucune réservation locale.</p> : (
        <ul className="capacityBlocks">{confirmed.map((block) => (
          <li key={block.id}><span>{describe(block)} · tâche {block.task_id.slice(0, 8)}
            {block.segment_id ? ` / segment ${block.segment_id.slice(0, 8)}` : ""}</span></li>
        ))}</ul>
      )}
    </div>
  );
}
