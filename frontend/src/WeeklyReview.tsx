import { apiFetch } from "./auth";
import { useEffect, useState } from "react";
import { BehaviorPanel } from "./BehaviorPanel";

type WeeklyAction = "RECIRCULATE" | "POSTPONE" | "REVIEW_LATER" | "DELEGATE" | "ABANDON";
type SubjectKind = "TASK" | "PROJECT";
type WeeklyTask = {
  task_id: string;
  title: string;
  project_id: string | null;
  status: string;
  protection: string;
  due_at: string | null;
  next_action: string | null;
  last_interaction_at: string | null;
};
type WeeklyProject = {
  project_id: string;
  title: string;
  open_task_count: number;
  actionable_count: number;
};
type Decision = {
  subject_kind: SubjectKind;
  subject_id: string;
  action: WeeklyAction;
  review_on: string | null;
  revision: number;
  decided_at: string;
};
type Weekly = {
  week_start: string;
  timezone_name: string;
  capacity_if_all_open: {
    available_minutes: number;
    known_demand_minutes: number;
    unestimated_units: number;
    remaining_minutes: number;
    status: string;
  };
  manual_block_count: number;
  projects: WeeklyProject[];
  projects_without_next_action: WeeklyProject[];
  protected: WeeklyTask[];
  drifted: WeeklyTask[];
  no_recent_interaction: WeeklyTask[];
  activity_unknown: WeeklyTask[];
  inbox: WeeklyTask[];
  decisions: Decision[];
  calendar_written: false;
  tasks_modified: false;
  is_hypothetical: true;
};

function mondayLocal(): string {
  const day = new Date();
  const offset = (day.getDay() + 6) % 7;
  day.setDate(day.getDate() - offset);
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, "0"),
    String(day.getDate()).padStart(2, "0")].join("-");
}

function shiftDays(value: string, days: number): string {
  const date = new Date(value + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : "Revue hebdomadaire indisponible.");
  }
  return response.json() as Promise<T>;
}

const actionLabels: Record<WeeklyAction, string> = {
  RECIRCULATE: "Remettre en circulation",
  POSTPONE: "Reporter la revue",
  REVIEW_LATER: "Fixer la prochaine revue",
  DELEGATE: "Envisager une délégation",
  ABANDON: "Envisager un abandon",
};

function DecisionForm({ kind, id, title, week, zone, previous, onSaved }: {
  kind: SubjectKind;
  id: string;
  title: string;
  week: string;
  zone: string;
  previous?: Decision;
  onSaved: () => void;
}) {
  const [action, setAction] = useState<WeeklyAction | "">(previous?.action ?? "");
  const [reviewOn, setReviewOn] = useState(previous?.review_on ?? shiftDays(week, 7));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setAction(previous?.action ?? "");
    setReviewOn(previous?.review_on ?? shiftDays(week, 7));
    setError("");
  }, [previous?.revision, previous?.action, previous?.review_on, week, id]);

  async function save() {
    if (!action) return;
    if (action === "ABANDON" &&
      !window.confirm("Consigner une intention d'abandon pour « " + title + " » ? L'élément ne sera pas fermé automatiquement.")) return;
    setBusy(true);
    setError("");
    try {
      await api("/api/review/weekly/decide", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          week_start: week, timezone_name: zone, subject_kind: kind,
          subject_id: id, action,
          review_on: action === "POSTPONE" || action === "REVIEW_LATER" ? reviewOn : null,
          expected_revision: previous?.revision ?? 0, confirmed: true,
        }),
      });
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Décision non enregistrée.");
    } finally {
      setBusy(false);
    }
  }

  const needsDate = action === "POSTPONE" || action === "REVIEW_LATER";
  return (
    <div className="weeklyChoice">
      {previous && <p className="muted">Dernière intention consignée : {actionLabels[previous.action]}
        {previous.review_on ? " — revue " + previous.review_on : ""}. Révision {previous.revision}.</p>}
      <label>Décision de revue pour {title}
        <select value={action} onChange={(e) => setAction(e.target.value as WeeklyAction | "")}>
          <option value="">Choisir une intention…</option>
          {Object.entries(actionLabels).map(([value, label]) =>
            <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {needsDate && <label>Prochaine date de revue
        <input type="date" min={shiftDays(week, 7)} value={reviewOn}
          onChange={(e) => setReviewOn(e.target.value)} />
      </label>}
      <button type="button" disabled={busy || !action ||
        (needsDate && (!reviewOn || reviewOn < shiftDays(week, 7)))}
        onClick={() => void save()}>
        {busy ? "Enregistrement…" : "Confirmer cette intention"}
      </button>
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}

function TaskList({ title, items, week, zone, decisions, onSaved, empty }: {
  title: string; items: WeeklyTask[]; week: string; zone: string;
  decisions: Decision[]; onSaved: () => void; empty: string;
}) {
  return (
    <section>
      <h3>{title} ({items.length})</h3>
      {!items.length ? <p className="empty">{empty}</p> : (
        <ul className="dailyList">
          {items.map((item) => (
            <li key={item.task_id}>
              <strong>{item.title}</strong>
              <p className="muted">{item.status} · {item.protection}
                {item.due_at ? " · Échéance : " + item.due_at.slice(0, 10) : ""}
              </p>
              {item.next_action && <p>Prochaine action : {item.next_action}</p>}
              <DecisionForm key={item.task_id + week} kind="TASK" id={item.task_id}
                title={item.title} week={week} zone={zone} onSaved={onSaved}
                previous={decisions.find((d) => d.subject_kind === "TASK" && d.subject_id === item.task_id)} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function WeeklyReview() {
  const [week, setWeek] = useState(mondayLocal);
  const [version, setVersion] = useState(0);
  const [weekly, setWeekly] = useState<Weekly | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const reload = () => setVersion((v) => v + 1);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<Weekly>("/api/review/weekly?week_start=" + encodeURIComponent(week)
      + "&timezone_name=" + encodeURIComponent(zone))
      .then((value) => { if (active) setWeekly(value); })
      .catch((err: unknown) => {
        if (active) {
          setWeekly(null);
          setError(err instanceof Error ? err.message : "Lecture hebdomadaire impossible.");
        }
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [week, zone, version]);

  return (
    <section className="inbox dailyPanel" aria-label="Revue hebdomadaire">
      <div className="sectionHeading">
        <h2>Revue hebdomadaire</h2>
        <button type="button" onClick={reload}>Actualiser les faits</button>
      </div>
      <label>Semaine (lundi)
        <input type="date" value={week} onChange={(e) => {
          const next = e.target.value;
          if (!next) return;
          const day = new Date(next + "T12:00:00Z");
          if (day.getUTCDay() !== 1) {
            setError("Choisir un lundi pour commencer la semaine.");
            return;
          }
          setWeek(next);
        }} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      {loading ? <p>Chargement de la revue hebdomadaire…</p> : weekly && (
        <>
          <p className="muted">Photographie des faits actuels pour la semaine choisie, non un état historique.
            Les choix sont consignés localement, sans modifier les tâches, les projets ni le calendrier.
            Appliquer les changements réels dans leurs commandes dédiées.</p>
          <BehaviorPanel refreshKey={week + ":" + version} />
          <h3>Capacité hebdomadaire — simulation de toutes les tâches ouvertes</h3>
          <p>Disponibilité manuelle : {weekly.capacity_if_all_open.available_minutes} min
            ({weekly.manual_block_count} bloc(s)); charge connue : {weekly.capacity_if_all_open.known_demand_minutes} min;
            unités sans estimation : {weekly.capacity_if_all_open.unestimated_units};
            verdict hypothétique : <strong>{weekly.capacity_if_all_open.status}</strong>.</p>
          {weekly.manual_block_count === 0 &&
            <p className="muted">Aucun bloc manuel : disponibilité inconnue, pas de capacité présumée.</p>}
          <h3>Projets actifs ({weekly.projects.length})</h3>
          {weekly.projects.length ? (
            <ul className="dailyList">{weekly.projects.map((project) => (
              <li key={project.project_id}>
                <strong>{project.title}</strong>
                <p>{project.open_task_count} tâche(s) ouverte(s) · {project.actionable_count} prochaine(s) action(s)</p>
                {project.actionable_count === 0 && <p>Projet sans prochaine action exploitable.</p>}
                <DecisionForm key={project.project_id + week} kind="PROJECT" id={project.project_id}
                  title={project.title} week={week} zone={zone} onSaved={reload}
                  previous={weekly.decisions.find((d) =>
                    d.subject_kind === "PROJECT" && d.subject_id === project.project_id)} />
              </li>
            ))}</ul>
          ) : <p className="empty">Aucun projet actif.</p>}
          <p className="muted">{weekly.projects_without_next_action.length} projet(s) actif(s) sans prochaine action exploitable.</p>
          <TaskList title="Tâches protégées" items={weekly.protected} week={week} zone={zone}
            decisions={weekly.decisions} onSaved={reload} empty="Aucune tâche protégée ouverte." />
          <TaskList title="Backlog avec échéance antérieure à cette semaine" items={weekly.drifted}
            week={week} zone={zone} decisions={weekly.decisions} onSaved={reload}
            empty="Aucune échéance antérieure ouverte." />
          <TaskList title="Sans interaction observée depuis 14 jours" items={weekly.no_recent_interaction}
            week={week} zone={zone} decisions={weekly.decisions} onSaved={reload}
            empty="Aucun élément ancien sur la base de l'historique connu." />
          {weekly.activity_unknown.length > 0 &&
            <p className="muted">{weekly.activity_unknown.length} élément(s) sans historique observé :
              l'absence de donnée ne signifie pas absence de travail.</p>}
          <TaskList title="Inbox à clarifier" items={weekly.inbox} week={week} zone={zone}
            decisions={weekly.decisions} onSaved={reload} empty="Inbox vide." />
          <h3>Intentions de revue enregistrées ({weekly.decisions.length})</h3>
          {weekly.decisions.length ? (
            <ul className="dailyList">{weekly.decisions.map((decision) => (
              <li key={decision.subject_kind + decision.subject_id}>
                {decision.subject_kind} {decision.subject_id} : {actionLabels[decision.action]}
                {decision.review_on ? " — " + decision.review_on : ""}
              </li>
            ))}</ul>
          ) : <p className="empty">Aucune décision de revue confirmée pour cette semaine.</p>}
        </>
      )}
    </section>
  );
}
