import { FormEvent, useEffect, useState } from "react";

type WorkType = { id: string; name: string };
type Task = { id: string; title: string; status: string };

type AvailabilityBlock = {
  id: string;
  starts_at: string;
  ends_at: string;
  work_type_id: string | null;
  minutes: number;
};
type Bucket = {
  work_type_id: string | null;
  available_minutes: number;
  known_demand_minutes: number;
  unestimated_units: number;
  remaining_minutes: number;
  status: "FEASIBLE" | "INCOMPLETE" | "OVER_CAPACITY";
};
type Evaluation = {
  status: Bucket["status"];
  available_minutes: number;
  known_demand_minutes: number;
  remaining_minutes: number;
  unestimated_units: number;
  by_work_type: Bucket[];
};
type Week = { blocks: AvailabilityBlock[]; capacity: Evaluation };

function localDate(day: Date): string {
  return [
    day.getFullYear(),
    String(day.getMonth() + 1).padStart(2, "0"),
    String(day.getDate()).padStart(2, "0"),
  ].join("-");
}

function monday(value: string): string {
  const day = new Date(value + "T12:00:00");
  day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
  return localDate(day);
}

function localOffset(value: string): string {
  const date = new Date(value);
  const minutes = -date.getTimezoneOffset();
  const sign = minutes >= 0 ? "+" : "-";
  const absolute = Math.abs(minutes);
  return `${value}:00${sign}${String(Math.floor(absolute / 60)).padStart(2, "0")}:${String(absolute % 60).padStart(2, "0")}`;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "Opération impossible.");
  }
  return response.json() as Promise<T>;
}

const headers = { "Content-Type": "application/json" };
const statusText: Record<Bucket["status"], string> = {
  FEASIBLE: "Charge estimée compatible avec la capacité",
  INCOMPLETE: "Faisabilité indéterminée : estimation(s) inconnue(s)",
  OVER_CAPACITY: "Capacité insuffisante pour la charge connue",
};

export function WeeklyCapacity({
  tasks, workTypes,
}: {
  tasks: Task[];
  workTypes: WorkType[];
}) {
  const [weekStart, setWeekStart] = useState(() => monday(localDate(new Date())));
  const [start, setStart] = useState(() => monday(localDate(new Date())) + "T09:00");
  const [end, setEnd] = useState(() => monday(localDate(new Date())) + "T10:00");
  const [workTypeId, setWorkTypeId] = useState("");
  const [data, setData] = useState<Week | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const eligible = tasks.filter(
    (task) => task.status === "TODO" || task.status === "IN_PROGRESS"
  );
  const labelFor = (id: string | null) =>
    id === null ? "Non classé" : workTypes.find((type) => type.id === id)?.name ?? "Type inconnu";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setEvaluation(null);
    request<Week>(`/api/capacity/weeks/${weekStart}`)
      .then((week) => { if (active) setData(week); })
      .catch((err: unknown) => {
        if (active) { setData(null); setError(err instanceof Error ? err.message : "Erreur de chargement."); }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [weekStart, reloadKey]);

  useEffect(() => { setEvaluation(null); }, [tasks]);

  function changeWeek(value: string) {
    if (!value) return;
    const week = monday(value);
    setWeekStart(week);
    setStart(week + "T09:00");
    setEnd(week + "T10:00");
    setSelected([]);
    setEvaluation(null);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await request<AvailabilityBlock>(`/api/capacity/weeks/${weekStart}/blocks`, {
        method: "POST", headers,
        body: JSON.stringify({
          starts_at: localOffset(start),
          ends_at: localOffset(end),
          work_type_id: workTypeId || null,
        }),
      });
      setReloadKey((value) => value + 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec de création du bloc.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/capacity/weeks/${weekStart}/blocks/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Échec de suppression du bloc.");
      setReloadKey((value) => value + 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Erreur.");
    } finally {
      setBusy(false);
    }
  }

  async function evaluate() {
    setBusy(true); setError(""); setEvaluation(null);
    try {
      const ids = selected.filter((id) => eligible.some((task) => task.id === id));
      setEvaluation(await request<Evaluation>(`/api/capacity/weeks/${weekStart}/evaluate`, {
        method: "POST", headers, body: JSON.stringify({ task_ids: ids }),
      }));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Évaluation impossible.");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string, checked: boolean) {
    setSelected((previous) =>
      checked ? [...previous, id] : previous.filter((current) => current !== id)
    );
    setEvaluation(null);
  }

  return (
    <section className="inbox capacityPanel">
      <h2>Capacité hebdomadaire</h2>
      <p className="muted">Blocs disponibles saisis manuellement. Chaque type de travail a sa propre capacité. La vérification est une simulation sans changement au plan.</p>
      <label>Semaine du lundi
        <input type="date" value={weekStart} onChange={(event) => changeWeek(event.target.value)} />
      </label>
      {error && <p role="alert" className="error">{error}</p>}
      {loading ? <p>Chargement des disponibilités…</p> : (
        <>
          <p><strong>{data?.capacity.available_minutes ?? 0} min disponibles</strong> cette semaine</p>
          {data?.blocks.length === 0 ? <p className="empty">Aucun bloc défini pour cette semaine.</p> : (
            <ul className="capacityBlocks">
              {data?.blocks.map((block) => (
                <li key={block.id}>
                  <span>{new Date(block.starts_at).toLocaleString()} – {new Date(block.ends_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {block.minutes} min · {labelFor(block.work_type_id)}</span>
                  <button type="button" disabled={busy} onClick={() => void remove(block.id)}>Supprimer</button>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={(event) => void save(event)} className="capacityForm">
            <div className="detailGrid">
              <label>Début disponible<input required type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
              <label>Fin disponible<input required type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
              <label>Type de travail
                <select value={workTypeId} onChange={(event) => setWorkTypeId(event.target.value)}>
                  <option value="">Non classé</option>
                  {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                </select>
              </label>
            </div>
            <button disabled={busy} type="submit">Ajouter un bloc disponible</button>
          </form>
          <h3>Vérifier une sélection pour cette semaine</h3>
          {eligible.length === 0 ? <p className="empty">Aucune tâche clarifiée ouverte à évaluer.</p> : (
            <fieldset className="capacitySelection">
              <legend>Tâches candidates (aucune affectation automatique)</legend>
              {eligible.map((task) => (
                <label key={task.id}>
                  <input type="checkbox" checked={selected.includes(task.id)}
                    onChange={(event) => toggle(task.id, event.target.checked)} />
                  {task.title}
                </label>
              ))}
            </fieldset>
          )}
          <button type="button" disabled={busy} onClick={() => void evaluate()}>Vérifier la faisabilité</button>
          {evaluation && (
            <div className="capacityResult" aria-live="polite">
              <strong>{statusText[evaluation.status]}</strong>
              <p>{evaluation.known_demand_minutes} min de charge connue / {evaluation.available_minutes} min disponibles.
                {evaluation.unestimated_units > 0 && ` ${evaluation.unestimated_units} unité(s) sans estimation.`}</p>
              {evaluation.by_work_type.map((bucket) => (
                <p key={bucket.work_type_id ?? "unclassified"}>
                  {labelFor(bucket.work_type_id)} : {bucket.known_demand_minutes}/{bucket.available_minutes} min
                  {bucket.unestimated_units > 0 && ` + ${bucket.unestimated_units} estimation(s) inconnue(s)`}
                  {" — "}{statusText[bucket.status]}
                </p>
              ))}
              <p className="muted">Ce diagnostic ne réserve aucun créneau et ne modifie aucune tâche.</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
