import { apiFetch } from "./auth";
import { useEffect, useState } from "react";

type Item = {
  task_id: string;
  title: string;
  protection: "PROTECTED" | "REPLANNABLE" | "FLEXIBLE";
  due_at: string | null;
  due_status: "OVERDUE" | "TODAY" | "LATER" | "NONE";
  next_action: string | null;
};
type Review = {
  day: string;
  timezone_name: string;
  week_start: string;
  today_available_minutes: number;
  manual_block_count: number;
  open_task_count: number;
  inbox_count: number;
  weekly_if_all_open: {
    status: "FEASIBLE" | "INCOMPLETE" | "OVER_CAPACITY";
    known_demand_minutes: number;
    available_minutes: number;
    unestimated_units: number;
  };
  must_review: Item[];
  may_slip: Item[];
  decisions: { code: string; message: string }[];
  is_hypothetical: boolean;
  has_daily_assignments: boolean;
};

function localToday(): string {
  const today = new Date();
  return [
    today.getFullYear(),
    String(today.getMonth() + 1).padStart(2, "0"),
    String(today.getDate()).padStart(2, "0"),
  ].join("-");
}

const dueLabel: Record<Item["due_status"], string> = {
  OVERDUE: "Échéance dépassée",
  TODAY: "Échéance aujourd'hui",
  LATER: "Échéance ultérieure",
  NONE: "Sans échéance",
};
const protectionLabel: Record<Item["protection"], string> = {
  PROTECTED: "Protégé",
  REPLANNABLE: "Replanifiable",
  FLEXIBLE: "Flexible",
};

function ReviewItems({ items }: { items: Item[] }) {
  if (!items.length) return <p className="empty">Aucun élément dans cette catégorie.</p>;
  return (
    <ul className="morningItems">
      {items.map((item) => (
        <li key={item.task_id}>
          <strong>{item.title}</strong>
          <span className="muted"> {protectionLabel[item.protection]} · {dueLabel[item.due_status]}</span>
          {item.next_action && <p>Prochaine action : {item.next_action}</p>}
        </li>
      ))}
    </ul>
  );
}

export function MorningReview({ tasks }: { tasks: { id: string }[] }) {
  const [day, setDay] = useState(localToday);
  const [refresh, setRefresh] = useState(0);
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    apiFetch(`/api/review/morning?day=${encodeURIComponent(day)}&timezone_name=${encodeURIComponent(zone)}`)
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : "Revue indisponible.");
        }
        return response.json() as Promise<Review>;
      })
      .then((value) => { if (active) setReview(value); })
      .catch((err: unknown) => {
        if (active) { setReview(null); setError(err instanceof Error ? err.message : "Erreur de revue."); }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [day, zone, refresh, tasks]);

  return (
    <section className="inbox morningPanel" aria-label="Revue du matin">
      <div className="sectionHeading">
        <h2>Revue du matin</h2>
        <button type="button" onClick={() => setRefresh((value) => value + 1)}>Actualiser</button>
      </div>
      <label>Journée
        <input type="date" value={day} onChange={(event) => setDay(event.target.value || localToday())} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      {loading ? <p>Chargement de la revue…</p> : review && (
        <div aria-live="polite">
          <p><strong>{review.today_available_minutes} min de disponibilité manuelle</strong> pour ce jour.</p>
          <p className="muted">Aucune tâche n'est encore assignée à une journée. Les blocs connus ne constituent pas un calendrier accepté.</p>
          <h3>À protéger ou à examiner aujourd'hui ({review.must_review.length})</h3>
          <ReviewItems items={review.must_review} />
          <h3>Reports envisageables, à confirmer ({review.may_slip.length})</h3>
          <ReviewItems items={review.may_slip} />
          <h3>Capacité : scénario hypothétique</h3>
          {review.manual_block_count === 0 ? (
            <p>Pas de blocs disponibles renseignés cette semaine : la surcharge réelle n'est pas déterminable.</p>
          ) : (
            <p>
              Si toutes les {review.open_task_count} tâches ouvertes étaient retenues cette semaine :
              {" "}<strong>{review.weekly_if_all_open.status === "OVER_CAPACITY" ? "surcharge potentielle" :
                review.weekly_if_all_open.status === "INCOMPLETE" ? "estimations incomplètes" : "charge connue compatible"}</strong>
              {" "}({review.weekly_if_all_open.known_demand_minutes}/{review.weekly_if_all_open.available_minutes} min connus).
              {review.weekly_if_all_open.unestimated_units > 0 &&
                ` ${review.weekly_if_all_open.unestimated_units} unité(s) sans estimation.`}
            </p>
          )}
          <h3>Décisions à examiner</h3>
          {review.decisions.length ? (
            <ul className="morningDecisions">
              {review.decisions.map((item) => <li key={item.code}>{item.message}</li>)}
            </ul>
          ) : <p className="empty">Rien ne demande d'arbitrage dans les données connues.</p>}
          <p className="muted">Lecture seule : aucun report, changement de priorité, plan ou créneau n'est appliqué.</p>
        </div>
      )}
    </section>
  );
}
