import { useEffect, useState } from "react";
import { BehaviorPanel } from "./BehaviorPanel";

type Task = {
  id: string;
  title: string;
  status: "INBOX" | "TODO" | "IN_PROGRESS" | "DONE" | "CANCELLED";
  protection: "PROTECTED" | "REPLANNABLE" | "FLEXIBLE";
};
type DailyItem = {
  task_id: string;
  title: string;
  status: Task["status"];
  protection: Task["protection"];
  due_at: string | null;
  next_action: string | null;
  reason: "UNFINISHED_DAY" | "REVIEW_DUE" | null;
  review_on: string | null;
};
type Daily = {
  day: string;
  timezone_name: string;
  state: "NOT_CHOSEN" | "OPEN" | "CLOSED";
  revision: number;
  selected_task_ids: string[];
  selected: DailyItem[];
  resurfaced: DailyItem[];
  followups: { task_id: string; review_on: string }[];
  calendar_written: false;
};

function localToday(): string {
  const now = new Date();
  return [now.getFullYear(), String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0")].join("-");
}

function tomorrow(day: string): string {
  const date = new Date(day + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function isOpen(status: Task["status"]): boolean {
  return status === "TODO" || status === "IN_PROGRESS";
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : "Revue quotidienne indisponible.");
  }
  return response.json() as Promise<T>;
}

export function DailyReview({ tasks }: { tasks: Task[] }) {
  const [day, setDay] = useState(localToday);
  const [refresh, setRefresh] = useState(0);
  const [daily, setDaily] = useState<Daily | null>(null);
  const [choices, setChoices] = useState<string[]>([]);
  const [reviewDates, setReviewDates] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    request<Daily>("/api/review/daily?day=" + encodeURIComponent(day)
      + "&timezone_name=" + encodeURIComponent(zone))
      .then((value) => {
        if (!active) return;
        setDaily(value);
        setChoices(value.selected_task_ids.filter((id) =>
          tasks.some((task) => task.id === id && isOpen(task.status))));
        setReviewDates(Object.fromEntries(value.selected
          .filter((item) => isOpen(item.status))
          .map((item) => [item.task_id, value.followups.find((f) =>
            f.task_id === item.task_id)?.review_on || tomorrow(day)])));
      })
      .catch((err: unknown) => {
        if (active) {
          setDaily(null);
          setError(err instanceof Error ? err.message : "Revue indisponible.");
        }
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [day, zone, refresh, tasks]);

  async function submit(path: "select" | "close", body: object) {
    setBusy(true);
    setError("");
    try {
      await request<Daily>("/api/review/daily/" + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setRefresh((value) => value + 1);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Opération impossible.");
    } finally {
      setBusy(false);
    }
  }

  function select() {
    if (!daily) return;
    void submit("select", {
      day, timezone_name: zone, task_ids: choices, expected_revision: daily.revision,
      reason: daily.state === "NOT_CHOSEN" ? "MORNING" : "SIGNIFICANT_EVENT",
      confirmed: true,
    });
  }

  function closeDay() {
    if (!daily) return;
    const open = daily.selected.filter((item) => isOpen(item.status));
    void submit("close", {
      day, timezone_name: zone, expected_revision: daily.revision,
      followups: open.map((item) => ({
        task_id: item.task_id, review_on: reviewDates[item.task_id] || tomorrow(day),
      })),
      confirmed: true,
    });
  }

  const candidates = tasks.filter((task) => isOpen(task.status));
  const openSelected = daily?.selected.filter((item) => isOpen(item.status)) || [];
  const datesValid = openSelected.every((item) =>
    (reviewDates[item.task_id] || "") > day);

  return (
    <section className="inbox dailyPanel" aria-label="Revue quotidienne">
      <div className="sectionHeading">
        <h2>Revue quotidienne</h2>
        <button type="button" disabled={busy} onClick={() => setRefresh((v) => v + 1)}>Actualiser les faits</button>
      </div>
      <label>Journée
        <input type="date" value={day} onChange={(e) => setDay(e.target.value || localToday())} />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      {loading ? <p>Chargement de la revue quotidienne…</p> : daily && (
        <>
          <p className="muted">
            {daily.state === "NOT_CHOSEN" ? "Aucun choix enregistré pour ce jour." :
              daily.state === "OPEN" ? "Choix du jour enregistré localement." : "Journée fermée explicitement."}
            {" "}Aucune tâche ni aucun événement de calendrier n'est modifié par cette revue.
          </p>
          <BehaviorPanel refreshKey={day + ":" + refresh} />
          <h3>Éléments à remettre en évidence ({daily.resurfaced.length})</h3>
          {daily.resurfaced.length ? (
            <ul className="dailyList">
              {daily.resurfaced.map((item) => (
                <li key={item.task_id}>
                  <strong>{item.title}</strong>
                  <p>{item.reason === "REVIEW_DUE" ?
                    "Date de revue choisie atteinte : " + item.review_on :
                    "Une journée précédente est restée ouverte : décider de la suite."}</p>
                  {item.next_action && <p>Prochaine action : {item.next_action}</p>}
                </li>
              ))}
            </ul>
          ) : <p className="empty">Aucune décision antérieure à réexaminer actuellement.</p>}

          {daily.state !== "CLOSED" && (
            <>
              <h3>{daily.state === "NOT_CHOSEN" ? "Matin : choisir le travail" :
                "Journée : réévaluer après un événement significatif"}</h3>
              <p className="muted">Ce choix représente une intention, pas une affectation d'horaire. Vérifier la capacité dans la revue du matin.</p>
              {candidates.length ? (
                <ul className="dailyChoices">
                  {candidates.map((task) => (
                    <li key={task.id}>
                      <label>
                        <input type="checkbox" checked={choices.includes(task.id)}
                          onChange={(e) => setChoices((current) => e.target.checked ?
                            [...current, task.id] : current.filter((id) => id !== task.id))} />
                        <span>{task.title} — {task.protection === "PROTECTED" ?
                          "protégé" : task.protection === "FLEXIBLE" ? "flexible" : "replanifiable"}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              ) : <p className="empty">Aucune tâche ouverte clarifiée. Un choix vide est permis.</p>}
              <button type="button" disabled={busy} onClick={select}>
                {daily.state === "NOT_CHOSEN" ? "Confirmer le choix du matin" :
                  "Confirmer la nouvelle sélection"}
              </button>
              {daily.state === "OPEN" && (
                <p className="muted">En cas de nouvel imprévu, actualiser les faits puis confirmer seulement les changements voulus.</p>
              )}
            </>
          )}

          {daily.state !== "NOT_CHOSEN" && (
            <>
              <h3>Choix enregistré ({daily.selected.length})</h3>
              {daily.selected.length ? (
                <ul className="dailyList">
                  {daily.selected.map((item) => (
                    <li key={item.task_id}>
                      <strong>{item.title}</strong> <span className="muted">({item.status})</span>
                      {item.next_action && <p>Prochaine action : {item.next_action}</p>}
                    </li>
                  ))}
                </ul>
              ) : <p className="empty">Aucune tâche retenue ce jour.</p>}
            </>
          )}

          {daily.state === "OPEN" && (
            <>
              <h3>Fin de journée : décider de la suite</h3>
              <p>Pour chaque tâche encore ouverte, choisir une prochaine date de revue.
                La fermeture ne termine ni ne reporte automatiquement les tâches.</p>
              {openSelected.map((item) => (
                <label key={item.task_id}>{item.title} — prochaine revue
                  <input type="date" min={tomorrow(day)}
                    value={reviewDates[item.task_id] || tomorrow(day)}
                    onChange={(e) => setReviewDates((current) => ({
                      ...current, [item.task_id]: e.target.value,
                    }))} />
                </label>
              ))}
              {openSelected.length === 0 && <p className="muted">Aucune tâche sélectionnée encore ouverte ne nécessite une date.</p>}
              <button type="button" disabled={busy || !datesValid} onClick={closeDay}>
                Confirmer et fermer cette journée
              </button>
            </>
          )}
          {daily.state === "CLOSED" && (
            <>
              <h3>Prochaines revues convenues</h3>
              {daily.followups.length ? (
                <ul className="dailyList">
                  {daily.followups.map((item) => (
                    <li key={item.task_id}>
                      {daily.selected.find((task) => task.task_id === item.task_id)?.title || item.task_id}
                      {" — "}{item.review_on}
                    </li>
                  ))}
                </ul>
              ) : <p className="empty">Aucune date de suivi requise.</p>}
            </>
          )}
        </>
      )}
    </section>
  );
}
