import { apiFetch } from "./auth";
import { useEffect, useState } from "react";

type Trend = {
  code: string;
  scope: string;
  work_type_id: string | null;
  sample_size: number;
  distinct_tasks: number;
  minimum_samples: number;
  uncertainty: "LIMITED";
  description: string;
  data_quality: "UNVERIFIED";
};
type Intervention = {
  task_id: string;
  task_title: string;
  code: string;
  observation: string;
  suggestion: string;
  data_quality: "UNVERIFIED" | "UNKNOWN";
  requires_confirmation: true;
};
type Projection = {
  as_of: string;
  minimum_samples: number;
  trends: Trend[];
  interventions: Intervention[];
  limitations: string[];
  changes_applied: false;
};

export function BehaviorPanel({ refreshKey }: { refreshKey: string | number }) {
  const [projection, setProjection] = useState<Projection | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    apiFetch("/api/behavior").then(async (response) => {
      if (!response.ok) throw new Error("Les observations sont temporairement indisponibles.");
      return response.json() as Promise<Projection>;
    }).then((value) => {
      if (active) setProjection(value);
    }).catch((reason: unknown) => {
      if (active) {
        setProjection(null);
        setError(reason instanceof Error ? reason.message : "Lecture impossible.");
      }
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [refreshKey]);

  return (
    <section aria-label="Observations comportementales" className="weeklyChoice">
      <h3>Observations et pistes facultatives</h3>
      <p className="muted">Lecture des faits actuels, non reconstruction de la date de revue.
        Aucun suivi passif, diagnostic ou changement automatique.</p>
      {loading && <p>Chargement des observations…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {projection && (
        <>
          <h4>Tendances observées ({projection.trends.length})</h4>
          {projection.trends.length === 0 ?
            <p className="muted">Données insuffisantes pour afficher une tendance
              (au moins {projection.minimum_samples} unités ou tâches indépendantes).</p> :
            <ul className="dailyList">{projection.trends.map((item) => (
              <li key={item.code + (item.work_type_id || "")}>
                <strong>{item.code.replaceAll("_", " ").toLowerCase()}</strong>
                <p>{item.description}</p>
                <p className="muted">{item.sample_size} observations, {item.distinct_tasks} tâches/unités;
                  seuil {item.minimum_samples} · données incomplètes possibles.</p>
              </li>
            ))}</ul>}
          <h4>Éléments à considérer ({projection.interventions.length})</h4>
          {projection.interventions.length === 0 ?
            <p className="muted">Aucune intervention supplémentaire suggérée actuellement.</p> :
            <ul className="dailyList">{projection.interventions.map((item) => (
              <li key={item.task_id + item.code}>
                <strong>{item.task_title}</strong>
                <p>{item.observation}</p>
                <p>Piste à choisir, non appliquée : {item.suggestion}</p>
                {item.data_quality === "UNKNOWN" &&
                  <p className="muted">Historique incomplet ou non disponible : l'activité est inconnue.</p>}
              </li>
            ))}</ul>}
          <p className="muted">Utiliser les commandes existantes (sélection, revue, amorçage ou session)
            pour confirmer une suite. L'absence d'interaction enregistrée n'est pas un échec.</p>
          <p className="muted">{projection.limitations.join(" ")}</p>
        </>
      )}
    </section>
  );
}
