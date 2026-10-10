import { apiFetch } from "./auth";
import { useState } from "react";

type SuggestedItem = {
  title: string;
  duration_min_minutes: number | null;
  duration_max_minutes: number | null;
  depends_on: number[];
};
type DecompositionSuggestion = {
  task_id: string;
  state: "PROPOSED";
  source: "AI_SUGGESTION";
  segments: SuggestedItem[];
  subtasks: SuggestedItem[];
  clarification_questions: string[];
};

function duration(item: SuggestedItem): string {
  if (item.duration_min_minutes === null || item.duration_max_minutes === null)
    return "Durée à préciser";
  if (item.duration_min_minutes === item.duration_max_minutes)
    return item.duration_min_minutes + " min suggérées";
  return item.duration_min_minutes + "–" + item.duration_max_minutes + " min suggérées";
}

export function DecompositionAssistant({
  taskId, onPrepareSegment,
}: {
  taskId: string;
  onPrepareSegment: (title: string) => void;
}) {
  const [proposal, setProposal] = useState<DecompositionSuggestion | null>(null);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function requestProposal() {
    setWorking(true);
    setError("");
    setProposal(null);
    try {
      const response = await apiFetch("/api/tasks/" + taskId + "/decomposition-suggestions", {
        method: "POST",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(typeof data?.detail === "string"
          ? data.detail : "Suggestions indisponibles.");
      }
      setProposal(await response.json() as DecompositionSuggestion);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Suggestions indisponibles.");
    } finally {
      setWorking(false);
    }
  }

  function items(list: SuggestedItem[], allowPrepare: boolean) {
    return (
      <ol className="segmentList">
        {list.map((item, index) => (
          <li key={index}>
            <strong>{item.title}</strong>
            <p className="muted">{duration(item)}</p>
            {item.depends_on.length > 0 && (
              <p className="muted">Après : {item.depends_on.map(
                (position) => list[position - 1].title
              ).join(", ")}</p>
            )}
            {allowPrepare && (
              <button type="button" onClick={() => onPrepareSegment(item.title)}>
                Reprendre dans le formulaire
              </button>
            )}
          </li>
        ))}
      </ol>
    );
  }

  return (
    <section className="decompositionPanel" aria-label="Décomposition assistée">
      <h4>Décomposition assistée par IA</h4>
      <p className="muted">
        Sur demande, le titre, les notes (jusqu'à 4 000 caractères), l'estimation
        et les segments ouverts de cette tâche sont transmis à OpenAI.
        Les durées et dépendances sont des hypothèses à vérifier.
        Aucune suggestion n'est enregistrée automatiquement.
      </p>
      <button type="button" disabled={working} onClick={() => void requestProposal()}>
        {working ? "Analyse…" : proposal ? "Regénérer les suggestions" : "Proposer une décomposition"}
      </button>
      {error && <p role="alert" className="error">{error}</p>}
      {proposal && (
        <div aria-live="polite">
          <p className="muted">Proposition IA non appliquée. Les sous-tâches et dépendances ne sont pas persistées.</p>
          {proposal.segments.length > 0 && (
            <>
              <h4>Segments amorçables suggérés</h4>
              {items(proposal.segments, true)}
            </>
          )}
          {proposal.subtasks.length > 0 && (
            <>
              <h4>Sous-tâches suggérées (idées seulement)</h4>
              {items(proposal.subtasks, false)}
            </>
          )}
          {proposal.clarification_questions.length > 0 && (
            <>
              <h4>Questions à clarifier</h4>
              <ul>{proposal.clarification_questions.map((question, index) => (
                <li key={index}>{question}</li>
              ))}</ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
