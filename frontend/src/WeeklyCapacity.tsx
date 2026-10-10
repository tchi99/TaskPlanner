import { FormEvent, useEffect, useState } from "react";
import { TimeBlockPlanner } from "./TimeBlockPlanner";

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
type CalendarWeek = {
  week_start: string;
  timezone_name: string;
  manual_available_minutes: number;
  occupied_minutes: number;
  remaining_minutes: number;
  by_work_type: {
    work_type_id: string | null;
    manual_available_minutes: number;
    occupied_minutes: number;
    remaining_minutes: number;
  }[];
  commitments: {
    calendar_id: string;
    event_id: string;
    title: string;
    starts_at: string;
    ends_at: string;
  }[];
};
type ProposalOption = {
  id: string;
  kind: "KEEP" | "DEFER" | "REVIEW_SCOPE" | "CONSIDER_DELEGATION" | "CLARIFY_ESTIMATES";
  label: string;
  rationale: string;
  consequences: string[];
  capacity: Evaluation | null;
  requires_confirmation: boolean;
};
type Proposal = {
  id: string;
  state: "PROPOSED";
  facts: string[];
  baseline: Evaluation;
  options: ProposalOption[];
};
type Arbitration = {
  state: "PROPOSED";
  source: "AI_SUGGESTION";
  proposal: Proposal;
  explanations: {
    option_index: number;
    explanation: string;
    question: string | null;
  }[];
};

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
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [arbitration, setArbitration] = useState<Arbitration | null>(null);
  const [calendar, setCalendar] = useState<CalendarWeek | null>(null);
  const [calendarBusy, setCalendarBusy] = useState(false);
  const [calendarError, setCalendarError] = useState("");
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
    setEvaluation(null); setProposal(null); setArbitration(null); setCalendar(null); setCalendarError("");
    request<Week>(`/api/capacity/weeks/${weekStart}`)
      .then((week) => { if (active) setData(week); })
      .catch((err: unknown) => {
        if (active) { setData(null); setError(err instanceof Error ? err.message : "Erreur de chargement."); }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [weekStart, reloadKey]);

  useEffect(() => { setEvaluation(null); setProposal(null); setArbitration(null); }, [tasks]);

  function changeWeek(value: string) {
    if (!value) return;
    const week = monday(value);
    setWeekStart(week);
    setStart(week + "T09:00");
    setEnd(week + "T10:00");
    setSelected([]);
    setEvaluation(null); setProposal(null); setArbitration(null); setCalendar(null); setCalendarError("");
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
    setBusy(true); setError(""); setEvaluation(null); setProposal(null); setArbitration(null);
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

  async function propose() {
    setBusy(true); setError(""); setProposal(null); setArbitration(null);
    try {
      const ids = selected.filter((id) => eligible.some((task) => task.id === id));
      setProposal(await request<Proposal>("/api/capacity/weeks/" + weekStart + "/proposals", {
        method: "POST", headers, body: JSON.stringify({ task_ids: ids }),
      }));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Proposition impossible.");
    } finally {
      setBusy(false);
    }
  }

  async function assistArbitration() {
    setBusy(true); setError(""); setArbitration(null);
    try {
      const ids = selected.filter((id) => eligible.some((task) => task.id === id));
      const answer = await request<Arbitration>(
        "/api/capacity/weeks/" + weekStart + "/arbitration-suggestions", {
          method: "POST", headers, body: JSON.stringify({ task_ids: ids }),
        }
      );
      // The backend recomputes this snapshot; never attach advice to older options.
      setProposal(answer.proposal);
      setArbitration(answer);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Arbitrage assisté indisponible.");
    } finally {
      setBusy(false);
    }
  }

  async function loadCalendar() {
    setCalendarBusy(true); setCalendarError(""); setCalendar(null);
    try {
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const result = await request<CalendarWeek>(
        "/api/capacity/weeks/" + weekStart + "/calendar?timezone_name=" + encodeURIComponent(timezone)
      );
      setCalendar(result);
    } catch (err: unknown) {
      setCalendarError(err instanceof Error ? err.message : "Lecture du calendrier impossible.");
    } finally {
      setCalendarBusy(false);
    }
  }

  function toggle(id: string, checked: boolean) {
    setSelected((previous) =>
      checked ? [...previous, id] : previous.filter((current) => current !== id)
    );
    setEvaluation(null); setProposal(null); setArbitration(null);
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
          <h3>Contexte Google Calendar (lecture seule)</h3>
          <p className="muted">Les engagements occupés réduisent uniquement les blocs manuels qui les croisent.
            Les catégories de temps ne deviennent pas des tâches. Cette lecture n'altère ni les blocs ni les simulations existantes.</p>
          <button type="button" disabled={calendarBusy || busy}
            onClick={() => void loadCalendar()}>
            {calendarBusy ? "Lecture du calendrier…" : "Lire Google Calendar"}
          </button>
          {calendarError && <p className="error" role="alert">{calendarError}</p>}
          {calendar?.week_start === weekStart && (
            <div className="capacityResult" aria-live="polite">
              <strong>{calendar.remaining_minutes} min disponibles après engagements Google Calendar</strong>
              <p>{calendar.manual_available_minutes} min de blocs manuels − {calendar.occupied_minutes} min occupées
                à l'intérieur de ces blocs.</p>
              {calendar.by_work_type.map((bucket) => (
                <p key={bucket.work_type_id ?? "unclassified"}>
                  {labelFor(bucket.work_type_id)} : {bucket.remaining_minutes} min restantes
                  {" "}({bucket.occupied_minutes} min occupées sur {bucket.manual_available_minutes} min manuelles)
                </p>
              ))}
              {calendar.commitments.length === 0
                ? <p className="muted">Aucun engagement occupé trouvé pour cette semaine.</p>
                : <ul className="capacityBlocks">{calendar.commitments.map((event) => (
                  <li key={event.calendar_id + ":" + event.event_id}>
                    <span>{event.title} · {new Date(event.starts_at).toLocaleString()} –
                      {" "}{new Date(event.ends_at).toLocaleString()}</span>
                  </li>
                ))}</ul>}
              <p className="muted">Aucun événement n'est créé ou modifié. Les vérifications et propositions
                ci-dessous utilisent encore la capacité manuelle brute; elles n'appliquent pas cet ajustement.</p>
            </div>
          )}
          <h3>Vérifier une sélection pour cette semaine</h3>
          {eligible.length === 0 ? <p className="empty">Aucune tâche clarifiée ouverte à évaluer.</p> : (
            <fieldset className="capacitySelection">
              <legend>Tâches candidates (aucune affectation automatique)</legend>
              {eligible.map((task) => (
                <label key={task.id}>
                  <input type="checkbox" disabled={busy} checked={selected.includes(task.id)}
                    onChange={(event) => toggle(task.id, event.target.checked)} />
                  {task.title}
                </label>
              ))}
            </fieldset>
          )}
          <button type="button" disabled={busy} onClick={() => void evaluate()}>Vérifier la faisabilité</button>
          {" "}
          <button type="button" disabled={busy} onClick={() => void propose()}>Proposer des options</button>
          {" "}
          <button type="button" disabled={busy || !proposal}
            onClick={() => void assistArbitration()}>
            {busy ? "Traitement…" : "Expliquer les options avec l'IA"}
          </button>
          {proposal && (
            <div className="capacityResult" aria-live="polite">
              <h3>Options de plan — simulation seulement</h3>
              <p className="muted">L'arbitrage assisté est facultatif. Sur demande, les résumés des scénarios,
                chiffres de capacité et conséquences affichées sont transmis à OpenAI; aucun
                événement de calendrier ni note de tâche n'est transmis. L'IA n'établit pas
                les priorités et ne prend aucune décision à votre place.</p>
              <p><strong>{statusText[proposal.baseline.status]}</strong> : {proposal.baseline.known_demand_minutes}/{proposal.baseline.available_minutes} min connus.
                {proposal.baseline.unestimated_units > 0 && " Estimations inconnues : " + proposal.baseline.unestimated_units + "."}
              </p>
              <ul>
                {proposal.options.map((option, index) => (
                  <li key={option.id}>
                    <strong>{option.label}</strong>
                    <p>{option.rationale}</p>
                    {option.capacity ? (
                      <p>Simulation : {statusText[option.capacity.status]} —
                        {" "}{option.capacity.known_demand_minutes}/{option.capacity.available_minutes} min connus,
                        {" "}{option.capacity.unestimated_units} unité(s) non estimée(s).
                      </p>
                    ) : (
                      <p className="muted">Piste qualitative : effet sur la capacité non chiffré.</p>
                    )}
                    <ul>{option.consequences.map((item, index) => <li key={index}>{item}</li>)}</ul>
                    {arbitration?.explanations.find((item) => item.option_index === index) && (
                      <div>
                        <p><strong>Explication IA — suggestion non vérifiée :</strong>{" "}
                          {arbitration.explanations[index].explanation}</p>
                        {arbitration.explanations[index].question &&
                          <p className="muted">À clarifier : {arbitration.explanations[index].question}</p>}
                      </div>
                    )}
                    {option.requires_confirmation && <p className="muted">Un arbitrage explicite serait nécessaire avant toute application.</p>}
                  </li>
                ))}
              </ul>
              <p className="muted">Aucune option n'est acceptée ni appliquée. Aucune date ni réservation n'est créée.</p>
            </div>
          )}
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
          <TimeBlockPlanner
            key={weekStart + ":" + selected.join(",") + ":" + reloadKey}
            weekStart={weekStart}
            taskIds={selected.filter((id) => eligible.some((task) => task.id === id))}
          />
        </>
      )}
    </section>
  );
}
