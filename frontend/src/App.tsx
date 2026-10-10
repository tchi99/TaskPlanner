import { apiFetch } from "./auth";
import { FormEvent, useCallback, useEffect, useState } from "react";
import "./app.css";
import { TaskSegments } from "./TaskSegments";
import { WeeklyCapacity } from "./WeeklyCapacity";
import { MorningReview } from "./MorningReview";
import { DailyReview } from "./DailyReview";
import { WeeklyReview } from "./WeeklyReview";

type Task = {
  id: string;
  title: string;
  notes: string | null;
  status: "INBOX" | "TODO" | "IN_PROGRESS" | "DONE" | "CANCELLED";
  protection: "PROTECTED" | "REPLANNABLE" | "FLEXIBLE";
  estimated_minutes: number | null;
  due_at: string | null;
  created_at: string;
  project_id: string | null;
  work_type_id: string | null;
};
type Project = { id: string; title: string; description: string | null; status: string };
type WorkType = { id: string; name: string; description: string | null };

async function jsonRequest<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const message = await response.json().catch(() => null);
    throw new Error(typeof message?.detail === "string" ? message.detail : "Impossible de terminer l'opération.");
  }
  return response.json() as Promise<T>;
}

const jsonHeaders = { "Content-Type": "application/json" };

function Clarifier({
  task, projects, workTypes, onSaved,
}: {
  task: Task;
  projects: Project[];
  workTypes: WorkType[];
  onSaved: () => Promise<void>;
}) {
  const [title, setTitle] = useState(task.title);
  const [notes, setNotes] = useState(task.notes ?? "");
  const [projectId, setProjectId] = useState(task.project_id ?? "");
  const [workTypeId, setWorkTypeId] = useState(task.work_type_id ?? "");
  const [minutes, setMinutes] = useState(task.estimated_minutes?.toString() ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function clarify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await jsonRequest<Task>(`/api/tasks/${task.id}/clarify`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify({
          title: title.trim(),
          notes: notes.trim() || null,
          project_id: projectId || null,
          work_type_id: workTypeId || null,
          estimated_minutes: minutes ? Number(minutes) : null,
        }),
      });
      await onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Erreur de clarification.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="clarifier" onSubmit={clarify}>
      <label>Tâche<input required maxLength={500} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <div className="detailGrid">
        <label>Projet
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">Sans projet</option>
            {projects.filter((project) => project.status === "ACTIVE").map((project) => (
              <option key={project.id} value={project.id}>{project.title}</option>
            ))}
          </select>
        </label>
        <label>Type de travail
          <select value={workTypeId} onChange={(e) => setWorkTypeId(e.target.value)}>
            <option value="">Non classé</option>
            {workTypes.map((type) => (
              <option key={type.id} value={type.id}>{type.name}</option>
            ))}
          </select>
        </label>
        <label>Estimation (minutes)
          <input type="number" min="1" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
        </label>
      </div>
      <button type="submit" disabled={saving || !title.trim()}>
        {saving ? "Clarification…" : "Clarifier et passer à faire"}
      </button>
      {error && <p role="alert" className="error">{error}</p>}
    </form>
  );
}

export function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workTypes, setWorkTypes] = useState<WorkType[]>([]);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [estimatedMinutes, setEstimatedMinutes] = useState("");
  const [newProject, setNewProject] = useState("");
  const [newWorkType, setNewWorkType] = useState("");
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const reload = useCallback(async () => {
    const [allTasks, allProjects, allTypes] = await Promise.all([
      jsonRequest<Task[]>("/api/tasks"),
      jsonRequest<Project[]>("/api/projects"),
      jsonRequest<WorkType[]>("/api/work-types"),
    ]);
    setTasks(allTasks);
    setProjects(allProjects);
    setWorkTypes(allTypes);
  }, []);

  useEffect(() => {
    reload()
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Erreur de chargement."))
      .finally(() => setLoading(false));
  }, [reload]);

  async function submitCapture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!title.trim()) return;
    setSaving(true);
    setError("");
    const body: Record<string, string | number> = { title: title.trim() };
    if (notes.trim()) body.notes = notes.trim();
    if (dueAt) body.due_at = new Date(dueAt).toISOString();
    if (estimatedMinutes) body.estimated_minutes = Number(estimatedMinutes);
    try {
      await jsonRequest<Task>("/api/tasks", {
        method: "POST", headers: jsonHeaders, body: JSON.stringify(body),
      });
      setTitle(""); setNotes(""); setDueAt(""); setEstimatedMinutes("");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec de capture.");
    } finally {
      setSaving(false);
    }
  }

  async function createReference(
    event: FormEvent<HTMLFormElement>,
    resource: "projects" | "work-types",
    value: string,
  ) {
    event.preventDefault();
    if (!value.trim()) return;
    setSaving(true);
    setError("");
    try {
      await jsonRequest(`/api/${resource}`, {
        method: "POST",
        headers: jsonHeaders,
        body: JSON.stringify(resource === "projects" ? { title: value.trim() } : { name: value.trim() }),
      });
      if (resource === "projects") setNewProject("");
      else setNewWorkType("");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec de création.");
    } finally {
      setSaving(false);
    }
  }

  async function assign(taskId: string, projectId: string) {
    setError("");
    try {
      await jsonRequest<Task>(`/api/tasks/${taskId}/project`, {
        method: "PATCH",
        headers: jsonHeaders,
        body: JSON.stringify({ project_id: projectId || null }),
      });
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec du rattachement.");
    }
  }

  async function changeProtection(taskId: string, protection: Task["protection"]) {
    const rank = { FLEXIBLE: 0, REPLANNABLE: 1, PROTECTED: 2 };
    const before = tasks.find((task) => task.id === taskId)?.protection;
    const downgrade = before !== undefined && rank[protection] < rank[before];
    if (downgrade && !window.confirm("Abaisser la protection de ce travail ? Confirmer cet arbitrage explicite.")) return;
    setError("");
    try {
      await jsonRequest<Task>(`/api/tasks/${taskId}/protection`, {
        method: "PATCH", headers: jsonHeaders,
        body: JSON.stringify({ protection, confirm_downgrade: downgrade }),
      });
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec du changement de protection.");
    }
  }

  const inbox = tasks.filter((task) => task.status === "INBOX");
  const clarified = tasks.filter((task) => task.status !== "INBOX");
  return (
    <main className="shell">
      <section className="hero">
        <p className="eyebrow">TaskPlanner</p>
        <h1>Capture ce qui te passe par la tête.</h1>
        <p>Le titre suffit. Tu pourras préciser le projet, le type et l'estimation ensuite.</p>
      </section>

      <form className="capture" onSubmit={submitCapture}>
        <div className="captureRow">
          <input autoFocus aria-label="Nouvelle tâche" placeholder="Nouvelle tâche…"
            value={title} onChange={(e) => setTitle(e.target.value)} />
          <button disabled={saving || !title.trim()} type="submit">
            {saving ? "Ajout…" : "Ajouter"}
          </button>
        </div>
        <details>
          <summary>Détails facultatifs</summary>
          <label>Notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
          <div className="detailGrid">
            <label>Échéance<input type="datetime-local" value={dueAt} onChange={(e) => setDueAt(e.target.value)} /></label>
            <label>Estimation (min)<input min="1" type="number" value={estimatedMinutes}
              onChange={(e) => setEstimatedMinutes(e.target.value)} /></label>
          </div>
        </details>
      </form>

      {error && <p className="error" role="alert">{error} <button type="button" onClick={() => { setError(""); void reload().catch(() => setError("Échec du rechargement.")); }}>Réessayer</button></p>}
      {loading ? <p>Chargement…</p> : (
        <>
          <MorningReview tasks={tasks} />
          <DailyReview tasks={tasks} />
          <WeeklyReview />
          <section className="inbox">
            <div className="sectionHeading"><h2>Inbox — à clarifier</h2><span>{inbox.length}</span></div>
            {inbox.length === 0 ? <p className="empty">Rien à clarifier pour l'instant.</p> : (
              <ul>{inbox.map((task) => (
                <li key={task.id}>
                  <Clarifier task={task} projects={projects} workTypes={workTypes} onSaved={reload} />
                </li>
              ))}</ul>
            )}
          </section>

          <section className="inbox">
            <h2>Projets et types de travail</h2>
            <div className="detailGrid">
              <form onSubmit={(e) => createReference(e, "projects", newProject)}>
                <label>Nouveau projet<input maxLength={500} value={newProject} onChange={(e) => setNewProject(e.target.value)} /></label>
                <button disabled={saving || !newProject.trim()}>Créer le projet</button>
              </form>
              <form onSubmit={(e) => createReference(e, "work-types", newWorkType)}>
                <label>Nouveau type de travail<input maxLength={200} value={newWorkType} onChange={(e) => setNewWorkType(e.target.value)} /></label>
                <button disabled={saving || !newWorkType.trim()}>Ajouter le type</button>
              </form>
            </div>
            {workTypes.length > 0 && <p className="muted">Types : {workTypes.map((type) => type.name).join(", ")}</p>}
          </section>

          <WeeklyCapacity tasks={tasks} workTypes={workTypes} />

          <section className="inbox">
            <h2>Tâches clarifiées</h2>
            {clarified.length === 0 ? <p className="empty">Aucune tâche clarifiée.</p> : (
              <ul>{clarified.map((task) => (
                <li key={task.id}>
                  <strong>{task.title}</strong>
                  <button className="detailToggle" type="button" onClick={() => setExpandedTaskId(expandedTaskId === task.id ? null : task.id)}>{expandedTaskId === task.id ? "Masquer les segments" : "Détail et segments"}</button>
                  <p className="muted">{task.status} · {task.estimated_minutes === null ? "Estimation inconnue" : `${task.estimated_minutes} min`}</p>
                  <label>Protection
                    <select value={task.protection} onChange={(e) => void changeProtection(task.id, e.target.value as Task["protection"])}>
                      <option value="PROTECTED">Protégé — ne doit pas dérailler</option>
                      <option value="REPLANNABLE">Important — replanifiable</option>
                      <option value="FLEXIBLE">Flexible — peut glisser</option>
                    </select>
                  </label>
                  <label>Projet
                    <select value={task.project_id ?? ""} onChange={(e) => void assign(task.id, e.target.value)}>
                      <option value="">Sans projet</option>
                      {projects.map((project) => (
                        <option key={project.id} value={project.id}
                          disabled={project.status !== "ACTIVE" && project.id !== task.project_id}>
                          {project.title}{project.status !== "ACTIVE" ? ` (${project.status})` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  {expandedTaskId === task.id && <TaskSegments key={task.id} taskId={task.id} workTypes={workTypes} onChanged={reload} />}
                </li>
              ))}</ul>
            )}
            <h3>Vue par projet</h3>
            {[...projects, { id: "", title: "Sans projet", description: null, status: "ACTIVE" }].map((project) => {
              const inProject = clarified.filter((task) => (task.project_id ?? "") === project.id);
              return (
                <div className="projectGroup" key={project.id || "unassigned"}>
                  <strong>{project.title}</strong> <small>{inProject.length} tâche(s)</small>
                  {inProject.length > 0 && <p className="muted">{inProject.map((task) => task.title).join(" · ")}</p>}
                </div>
              );
            })}
          </section>
        </>
      )}
    </main>
  );
}
