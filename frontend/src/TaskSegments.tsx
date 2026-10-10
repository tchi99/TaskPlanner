import { FormEvent, useEffect, useState } from "react";

type WorkType = { id: string; name: string };
type Segment = {
  id: string;
  title: string;
  position: number;
  status: string;
  estimated_minutes: number | null;
  work_type_id: string | null;
  effective_work_type_id: string | null;
  work_type_origin: string;
  effective_protection: string;
  allowed_actions: string[];
};
type TaskDetail = {
  id: string;
  title: string;
  status: string;
  segments: Segment[];
  next_action: { action_type: string; target_id: string; label: string } | null;
  effective_estimate: {
    source: string;
    known_subtotal_minutes: number;
    total_minutes: number | null;
    unestimated_units: number;
    incomplete: boolean;
  };
  progress: {
    total_segments: number;
    completed_segments: number;
    cancelled_segments: number;
    open_segments: number;
    completion_percent: number | null;
  };
  ready_for_completion: boolean;
  allowed_actions: string[];
};

const headers = { "Content-Type": "application/json" };

async function send(url: string, options?: RequestInit): Promise<TaskDetail> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const message = await response.json().catch(() => null);
    throw new Error(typeof message?.detail === "string" ? message.detail : "Échec de l'opération.");
  }
  return response.json() as Promise<TaskDetail>;
}

const taskActions: Record<string, string> = {
  START_TASK: "Commencer la tâche",
  COMPLETE_TASK: "Clôturer explicitement",
  CANCEL_TASK: "Annuler la tâche",
  REOPEN_TASK: "Rouvrir la tâche",
};

const segmentActions: Record<string, string> = {
  START: "Commencer",
  COMPLETE: "Terminer",
  CANCEL: "Annuler",
  REMOVE: "Supprimer",
};

export function TaskSegments({
  taskId, workTypes, onChanged,
}: {
  taskId: string;
  workTypes: WorkType[];
  onChanged: () => Promise<void>;
}) {
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newMinutes, setNewMinutes] = useState("");
  const [newType, setNewType] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editMinutes, setEditMinutes] = useState("");
  const [editType, setEditType] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setDetail(null);
    send(`/api/tasks/${taskId}/detail`)
      .then((result) => { if (active) setDetail(result); })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Échec du chargement.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [taskId]);

  async function mutate(path: string, method: string, body?: object) {
    setBusy(true);
    setError("");
    try {
      const updated = await send(`/api/tasks/${taskId}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
      });
      setDetail(updated);
      await onChanged();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Échec de l'opération.");
    } finally {
      setBusy(false);
    }
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newTitle.trim()) return;
    await mutate("/segments", "POST", {
      title: newTitle.trim(),
      estimated_minutes: newMinutes ? Number(newMinutes) : null,
      work_type_id: newType || null,
    });
    // A failed request leaves the form values available for correction.
    // The detail refetch is not needed: the mutation returns the new projection.
    // Keep text only if an error occurred.
  }

  function beginEdit(segment: Segment) {
    setEditing(segment.id);
    setEditTitle(segment.title);
    setEditMinutes(segment.estimated_minutes?.toString() ?? "");
    setEditType(segment.work_type_id ?? "");
  }

  async function edit(event: FormEvent<HTMLFormElement>, segment: Segment) {
    event.preventDefault();
    if (!editTitle.trim()) return;
    await mutate(`/segments/${segment.id}`, "PATCH", {
      title: editTitle.trim(),
      estimated_minutes: editMinutes ? Number(editMinutes) : null,
      work_type_id: editType || null,
    });
    // The edit panel stays visible so a rejected edit can be corrected.
  }

  function reorder(index: number, offset: number) {
    if (!detail) return;
    const ids = detail.segments.map((item) => item.id);
    const [id] = ids.splice(index, 1);
    ids.splice(index + offset, 0, id);
    void mutate("/segments/order", "PUT", { segment_ids: ids });
  }

  function actOnSegment(segment: Segment, action: string) {
    if (action === "REMOVE" && !window.confirm(
      "Supprimer définitivement ce segment jamais démarré ? Son historique sera conservé."
    )) return;
    const path = `/segments/${segment.id}`;
    void mutate(
      action === "REMOVE" ? path : `${path}/${action.toLowerCase()}`,
      action === "REMOVE" ? "DELETE" : "POST",
    );
  }

  if (loading) return <p className="muted">Chargement du détail…</p>;
  return (
    <section className="segmentPanel" aria-label="Détail et segments">
      {error && <p role="alert" className="error">{error}</p>}
      {!detail ? (
        <button type="button" onClick={() => {
          setLoading(true);
          send(`/api/tasks/${taskId}/detail`)
            .then(setDetail)
            .catch((err: unknown) => setError(err instanceof Error ? err.message : "Échec du chargement."))
            .finally(() => setLoading(false));
        }}>Réessayer</button>
      ) : (
        <>
          <div className="segmentSummary">
            <strong>Prochaine action</strong>
            <p>{detail.next_action?.label ?? "Aucune action ouverte."}</p>
            <strong>Estimation effective ({detail.effective_estimate.source === "SEGMENTS" ? "segments" : "tâche"})</strong>
            <p>{detail.effective_estimate.total_minutes === null
              ? `Inconnue · ${detail.effective_estimate.known_subtotal_minutes} min connues · ${detail.effective_estimate.unestimated_units} unité(s) non estimée(s)`
              : `${detail.effective_estimate.total_minutes} min`}</p>
            <strong>Progression</strong>
            <p>{detail.progress.total_segments === 0
              ? "Aucun segment"
              : `${detail.progress.completed_segments}/${detail.progress.total_segments} terminés · ${detail.progress.cancelled_segments} annulés · ${detail.progress.open_segments} ouverts`}</p>
            {detail.ready_for_completion && <p>Prête à être clôturée explicitement (aucune clôture automatique).</p>}
          </div>
          <div className="segmentActions">
            {detail.allowed_actions.filter((action) => action.endsWith("_TASK")).map((action) => (
              <button key={action} type="button" disabled={busy}
                onClick={() => void mutate(`/transition/${action.split("_")[0].toLowerCase()}`, "POST")}>
                {taskActions[action]}
              </button>
            ))}
          </div>
          <h4>Segments</h4>
          {detail.segments.length === 0 ? <p className="muted">Aucun segment pour cette tâche.</p> : (
            <ol className="segmentList">
              {detail.segments.map((segment, index) => (
                <li key={segment.id}>
                  <strong>{segment.title}</strong>
                  <p className="muted">
                    {segment.status} · {segment.estimated_minutes === null ? "Estimation inconnue" : `${segment.estimated_minutes} min`}
                    {" · "}{segment.work_type_origin === "SEGMENT_OVERRIDE" ? "Type spécifique" : segment.work_type_origin === "TASK_INHERITED" ? "Type hérité" : "Non classé"}
                    {" · "}{segment.effective_protection}
                  </p>
                  <div className="segmentActions">
                    {detail.allowed_actions.includes("REORDER_SEGMENTS") && index > 0 && (
                      <button type="button" disabled={busy} onClick={() => reorder(index, -1)}>Monter</button>
                    )}
                    {detail.allowed_actions.includes("REORDER_SEGMENTS") && index < detail.segments.length - 1 && (
                      <button type="button" disabled={busy} onClick={() => reorder(index, 1)}>Descendre</button>
                    )}
                    {segment.allowed_actions.includes("EDIT") && (
                      <button type="button" disabled={busy} onClick={() => beginEdit(segment)}>Modifier</button>
                    )}
                    {segment.allowed_actions.filter((action) => action !== "EDIT").map((action) => (
                      <button type="button" disabled={busy} key={action}
                        onClick={() => actOnSegment(segment, action)}>
                        {segmentActions[action]}
                      </button>
                    ))}
                  </div>
                  {editing === segment.id && (
                    <form className="segmentForm" onSubmit={(event) => void edit(event, segment)}>
                      <label>Titre<input maxLength={500} required value={editTitle} onChange={(event) => setEditTitle(event.target.value)} /></label>
                      <label>Estimation (min)<input type="number" min="1" value={editMinutes} onChange={(event) => setEditMinutes(event.target.value)} /></label>
                      <label>Type de travail
                        <select value={editType} onChange={(event) => setEditType(event.target.value)}>
                          <option value="">Hériter de la tâche</option>
                          {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                        </select>
                      </label>
                      <div className="segmentActions">
                        <button disabled={busy || !editTitle.trim()}>Enregistrer</button>
                        <button type="button" disabled={busy} onClick={() => setEditing(null)}>Fermer</button>
                      </div>
                    </form>
                  )}
                </li>
              ))}
            </ol>
          )}
          {detail.allowed_actions.includes("ADD_SEGMENT") && (
            <form className="segmentForm" onSubmit={(event) => void add(event)}>
              <h4>Ajouter un segment</h4>
              <label>Action concrète<input required maxLength={500} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} /></label>
              <label>Estimation (min)<input type="number" min="1" value={newMinutes} onChange={(e) => setNewMinutes(e.target.value)} /></label>
              <label>Type
                <select value={newType} onChange={(e) => setNewType(e.target.value)}>
                  <option value="">Hériter de la tâche</option>
                  {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                </select>
              </label>
              <button disabled={busy || !newTitle.trim()} type="submit">Ajouter le segment</button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
