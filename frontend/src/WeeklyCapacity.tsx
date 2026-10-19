import { apiFetch } from "./auth";
import { useEffect, useState } from "react";
import { TimeBlockPlanner } from "./TimeBlockPlanner";

type WorkType = { id: string; name: string };
type Task = { id: string; title: string; status: string };

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

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
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
  const [selected, setSelected] = useState<string[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [arbitration, setArbitration] = useState<Arbitration | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const eligible = tasks.filter(
    (task) => task.status === "TODO" || task.status === "IN_PROGRESS"
  );
  const labelFor = (id: string | null) =>
    id === null ? "Non classé" : workTypes.find((type) => type.id === id)?.name ?? "Type inconnu";

  useEffect(() => { setEvaluation(null); setProposal(null); setArbitration(null); }, [tasks]);

  function changeWeek(value: string) {
    if (!value) return;
    const week = monday(value);
    setWeekStart(week);
    setSelected([]);
    setEvaluation(null); setProposal(null); setArbitration(null);
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

  function toggle(id: string, checked: boolean) {
    setSelected((previous) =>
      checked ? [...previous, id] : previous.filter((current) => current !== id)
    );
    setEvaluation(null); setProposal(null); setArbitration(null);
  }

  return (
    <section className="inbox capacityPanel">
      <h2>Capacité hebdomadaire</h2>
      <p className="muted">Cette vue utilise les capacités et permissions configurées dans
        Disponibilités. Elle ne crée aucun bloc manuel parallèle.</p>
      <label>Semaine du lundi
        <input type="date" value={weekStart} onChange={(event) => changeWeek(event.target.value)} />
      </label>
      {error && <p role="alert" className="error">{error}</p>}
      <p className="muted">Évalue la sélection pour demander les minutes physiques calculées côté serveur.</p>
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
            key={weekStart + ":" + selected.join(",")}
            weekStart={weekStart}
            taskIds={selected.filter((id) => eligible.some((task) => task.id === id))}
            taskNames={Object.fromEntries(tasks.map((task) => [task.id, task.title]))}
            workTypeNames={Object.fromEntries(workTypes.map((type) => [type.id, type.name]))}
            onBookingChanged={() => { setEvaluation(null); setProposal(null); setArbitration(null); }}
          />
    </section>
  );
}
