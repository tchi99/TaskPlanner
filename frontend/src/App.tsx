import { FormEvent, useCallback, useEffect, useState } from "react";

type InboxTask = {
  id: string;
  title: string;
  notes: string | null;
  status: "INBOX";
  estimated_minutes: number | null;
  due_at: string | null;
  created_at: string;
};

export function App() {
  const [tasks, setTasks] = useState<InboxTask[]>([]);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [estimatedMinutes, setEstimatedMinutes] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const loadInbox = useCallback(async () => {
    const response = await fetch("/api/tasks/inbox");
    if (!response.ok) {
      throw new Error("Impossible de charger l'Inbox.");
    }
    setTasks(await response.json());
  }, []);

  useEffect(() => {
    loadInbox().catch((loadError: unknown) => {
      setError(loadError instanceof Error ? loadError.message : "Erreur inconnue.");
    });
  }, [loadInbox]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      return;
    }

    setSaving(true);
    setError("");

    const body: Record<string, string | number> = { title: trimmedTitle };
    if (notes.trim()) {
      body.notes = notes.trim();
    }
    if (dueAt) {
      body.due_at = new Date(dueAt).toISOString();
    }
    if (estimatedMinutes) {
      body.estimated_minutes = Number(estimatedMinutes);
    }

    try {
      const response = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error("La capture n'a pas pu être enregistrée.");
      }

      setTitle("");
      setNotes("");
      setDueAt("");
      setEstimatedMinutes("");
      await loadInbox();
    } catch (submitError: unknown) {
      setError(
        submitError instanceof Error ? submitError.message : "Erreur inconnue.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">TaskPlanner</p>
        <h1>Capture ce qui te passe par la tête.</h1>
        <p>Le titre suffit. Les détails peuvent attendre la clarification.</p>
      </section>

      <form className="capture" onSubmit={submit}>
        <div className="captureRow">
          <input
            autoFocus
            aria-label="Nouvelle tâche"
            placeholder="Nouvelle tâche…"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
          <button disabled={saving || !title.trim()} type="submit">
            {saving ? "Ajout…" : "Ajouter"}
          </button>
        </div>

        <details>
          <summary>Détails facultatifs</summary>
          <label>
            Notes
            <textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </label>
          <div className="detailGrid">
            <label>
              Échéance
              <input
                type="datetime-local"
                value={dueAt}
                onChange={(event) => setDueAt(event.target.value)}
              />
            </label>
            <label>
              Estimation (min)
              <input
                min="1"
                type="number"
                value={estimatedMinutes}
                onChange={(event) => setEstimatedMinutes(event.target.value)}
              />
            </label>
          </div>
        </details>

        {error && <p className="error">{error}</p>}
      </form>

      <section className="inbox">
        <div className="sectionHeading">
          <h2>Inbox</h2>
          <span>{tasks.length}</span>
        </div>

        {tasks.length === 0 ? (
          <p className="empty">Rien à clarifier pour l'instant.</p>
        ) : (
          <ul>
            {tasks.map((task) => (
              <li key={task.id}>
                <strong>{task.title}</strong>
                {task.notes && <p>{task.notes}</p>}
                <small>
                  {task.estimated_minutes
                    ? task.estimated_minutes + " min"
                    : "Estimation à préciser"}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
