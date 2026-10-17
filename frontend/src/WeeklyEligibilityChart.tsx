import { useEffect, useState } from "react";
import { apiFetch } from "./auth";
import { EligibilityContextEditor } from "./EligibilityContextEditor";
import type { ScopeCatalog } from "./ScheduleCategories";
import "./weekly-eligibility.css";

type WorkType = { id: string; name: string };
type TaskChoice = { id: string; title: string; status: string; work_type_id: string | null };
type SourceDetail = {
  series_id: string; revision: number; effective_from: string;
  valid_until: string | null; timezone_name: string;
  original_local_date: string; source: string;
};
type Choice = {
  work_type_id: string | null; priority_rank: number | null;
  exclusive: boolean; legacy_mode: string | null;
  sources: string[]; source_details: SourceDetail[];
};
type CivilPart = {
  starts_at: string; ends_at: string; starts_at_local: string; ends_at_local: string;
  local_date: string; weekday: number; start_minute: number; end_minute: number;
  day_minutes: number; minutes: number;
};
type Fragment = CivilPart & {
  scope_id: string; sources: string[]; null_residual: boolean;
  choices: Choice[]; verification: string;
};
type Occupation = CivilPart & {
  kind: "LOCAL_CONFIRMED" | "GOOGLE_VERIFIED"; source: string;
  task_id?: string; booking_id?: string; work_type_id?: string | null; title?: string;
};
type DayLayout = { local_date: string; weekday: number; starts_at: string; ends_at: string; minutes: number;
  ticks: { label: string; minute: number }[] };
type Issue = {
  code: string; starts_at: string; ends_at: string; sources: string[];
  booking_id: string | null; state: string; scope_ids: string[];
};
type Snapshot = {
  week_start: string; timezone_name: string; scope_id: string; read_only: boolean;
  calendar_state: "VERIFIED" | "UNAVAILABLE" | "NOT_CONFIGURED";
  calendar_checked: boolean; calendar_error: string | null;
  physical_minutes: number; verified_free_minutes: number | null;
  verified_occupied_minutes: number | null; local_occupied_minutes: number;
  potential_minutes: { work_type_id: string; minutes: number; non_additive: boolean }[];
  days: DayLayout[]; fragments: Fragment[]; occupations: Occupation[];
  issues: Issue[];
  expansion_issues: { code: string; series_id: string; original_local_date: string }[];
};
type Suggestion = {
  task_id: string; segment_id: string | null; label: string; work_type_id: string | null;
  scope_id: string | null; starts_at: string; ends_at: string; minutes: number;
  priority_rank: number | null; placement_reason: string | null;
  eligibility_sources: string[]; transferred_from: string | null;
};
type Proposal = {
  state: "PROPOSED"; calendar_checked: boolean; fingerprint: string; can_confirm: boolean;
  suggestions: Suggestion[];
  unplaced: { label: string; reason: string; remaining_minutes: number | null }[];
};
type Layer = "configuration" | "occupation" | "proposed";
type BarDetail = { title: string; dates: string; notes: string[] };
type EditTarget = {
  scopeId: string; workTypeId: string; seriesId: string | null;
  legacyRuleId: string | null; selectedDate: string;
};
const weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];

function timeLabel(value: string, zone: string): string {
  return new Intl.DateTimeFormat("fr-CA", {
    timeZone: zone, hour: "2-digit", minute: "2-digit", timeZoneName: "shortOffset",
  }).format(new Date(value));
}
function geometry(start: number, end: number, total: number) {
  return { left: (100 * start / total) + "%",
    width: (100 * (end - start) / total) + "%" };
}
function clipped(start: string, end: string, day: DayLayout) {
  const a = Math.max(Date.parse(start), Date.parse(day.starts_at));
  const b = Math.min(Date.parse(end), Date.parse(day.ends_at));
  if (a >= b) return null;
  return geometry((a - Date.parse(day.starts_at)) / 60000,
    (b - Date.parse(day.starts_at)) / 60000, day.minutes);
}
async function readApi<T>(url: string, options?: RequestInit): Promise<T> {
  const result = await apiFetch(url, options);
  if (!result.ok) {
    const body = await result.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail :
      "Lecture refusée (" + result.status + ").");
  }
  return result.json() as Promise<T>;
}

export function WeeklyEligibilityChart({ week, zone, scopeId, catalog, workTypes, tasks,
  onSelectScope }: {
  week: string; zone: string; scopeId: string | null; catalog: ScopeCatalog | null;
  workTypes: WorkType[]; tasks: TaskChoice[]; onSelectScope: (id: string) => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [layer, setLayer] = useState<Layer>("configuration");
  const [workTypeFilter, setWorkTypeFilter] = useState("");
  const [showPriority, setShowPriority] = useState(true);
  const [detail, setDetail] = useState<BarDetail | null>(null);
  const [editTargets, setEditTargets] = useState<EditTarget[]>([]);
  const [editorTarget, setEditorTarget] = useState<EditTarget | null>(null);
  const [taskId, setTaskId] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [proposalError, setProposalError] = useState("");
  const [previewBusy, setPreviewBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const selected = scopeId || catalog?.compatibility_scope_id || "";

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setSnapshot(null); setDetail(null);
    setEditTargets([]); setEditorTarget(null);
    setProposal(null); setProposalError("");
    const query = new URLSearchParams({ week_start: week, timezone_name: zone });
    if (scopeId) query.set("scope_id", scopeId);
    void readApi<Snapshot>("/api/availability/eligibility-week?" + query)
      .then((value) => { if (active) setSnapshot(value); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Grille indisponible.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [week, zone, scopeId, retry]);

  function label(id: string | null) {
    if (id === null) return "Général (NULL)";
    return workTypes.find((item) => item.id === id)?.name || "Type " + id.slice(0, 8);
  }
  function colorClass(id: string | null) {
    const index = workTypes.findIndex((item) => item.id === id);
    return "eligColor" + ((index < 0 ? 0 : index) % 6);
  }
  function showFragment(item: Fragment, choice: Choice) {
    setEditorTarget(null);
    const series = choice.exclusive ? [] : choice.source_details.filter(
      (source) => source.source.startsWith("ELIGIBILITY:"));
    const legacy = choice.exclusive ? choice.sources
      .filter((value) => value.startsWith("RULE:"))
      .map((value) => value.split(":")[1]).filter((id, index, values) => values.indexOf(id) === index) : [];
    const targets: EditTarget[] = choice.work_type_id === null ? [] : [
      ...series.map((source) => ({ scopeId: item.scope_id,
        workTypeId: choice.work_type_id!, seriesId: source.series_id,
        legacyRuleId: null, selectedDate: item.local_date })),
      ...legacy.map((id) => ({ scopeId: item.scope_id,
        workTypeId: choice.work_type_id!, seriesId: null,
        legacyRuleId: id, selectedDate: item.local_date })),
    ];
    setEditTargets(targets);
    setDetail({
      title: label(choice.work_type_id),
      dates: item.local_date + " · " + timeLabel(item.starts_at, zone) + " → " +
        timeLabel(item.ends_at, zone) + " · " + item.minutes + " min réelles",
      notes: [
        "Parent : " + (catalog?.scopes.find((v) => v.id === item.scope_id)?.name || item.scope_id),
        choice.priority_rank === null ? "Priorité contextuelle : neutre" :
          "Rang contextuel : " + choice.priority_rank,
        choice.exclusive ? "Affectation exclusive historique · " + (choice.legacy_mode || "stricte") :
          "Admissibilité partagée : aucun temps réservé",
        "Autres activités simultanément admissibles : " +
          (item.choices.filter((other) => other.work_type_id !== choice.work_type_id)
            .map((other) => label(other.work_type_id)).join(", ") || "aucune"),
        ...choice.source_details.map((v) => "Série " + v.series_id + " · révision " +
          v.revision + " · effet " + v.effective_from + " · " + v.timezone_name),
        "Provenances : " + choice.sources.join(" ; "),
      ],
    });
  }
  function showOccupation(item: Occupation) {
    setEditorTarget(null); setEditTargets([]);
    setDetail({
      title: item.kind === "GOOGLE_VERIFIED" ? "Google occupé vérifié" : "Réservation locale confirmée",
      dates: item.local_date + " · " + timeLabel(item.starts_at, zone) + " → " + timeLabel(item.ends_at, zone),
      notes: [item.title || (item.work_type_id ? label(item.work_type_id) : "Engagement"),
        "Provenance : " + item.source, "Occupation physique, pas une admissibilité"],
    });
  }
  async function previewTask() {
    if (!taskId) return;
    setPreviewBusy(true); setProposalError(""); setProposal(null);
    try {
      const value = await readApi<Proposal>(
        "/api/capacity/weeks/" + week + "/time-blocks/preview",
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_ids: [taskId], timezone_name: zone }) });
      setProposal(value);
    } catch (reason: unknown) {
      setProposalError(reason instanceof Error ? reason.message : "Aperçu impossible.");
    } finally { setPreviewBusy(false); }
  }
  const availableTasks = tasks.filter((task) =>
    (task.status === "TODO" || task.status === "IN_PROGRESS") && task.work_type_id);
  return <section className="availabilityCard eligibilityChart" aria-label="Vue hebdomadaire des admissibilités">
    <div className="availabilityCardHeading">
      <div><h3>Grille hebdomadaire · permissions et occupations</h3>
        <p className="muted">Une seule chronologie physique, plusieurs choix possibles par minute.</p></div>
      <button type="button" disabled={loading} onClick={() => setRetry((n) => n + 1)}>
        Actualiser la visualisation
      </button>
    </div>
    <div className="eligControls">
      <label>Parent
        <select aria-label="Parent de la visualisation" value={selected} onChange={(event) =>
          onSelectScope(event.target.value === catalog?.compatibility_scope_id ? "" : event.target.value)}>
          <option value={catalog?.compatibility_scope_id || ""}>Compatibilité (héritage)</option>
          {catalog?.scopes.filter((value) => !value.is_compatibility).map((scope) =>
            <option key={scope.id} value={scope.id}>{scope.name}</option>)}
        </select>
      </label>
      <label>Activité à afficher
        <select value={workTypeFilter} onChange={(event) => { setWorkTypeFilter(event.target.value); setDetail(null); }}>
          <option value="">Toutes les activités</option>
          {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
        </select>
      </label>
      <label><input type="checkbox" checked={showPriority}
        onChange={(event) => setShowPriority(event.target.checked)} /> Montrer les priorités</label>
    </div>
    <div className="eligTabs" role="group" aria-label="Couche de la visualisation">
      <button type="button" aria-pressed={layer === "configuration"} onClick={() => { setLayer("configuration"); setDetail(null); }}>
        Configuration
      </button>
      <button type="button" aria-pressed={layer === "occupation"} onClick={() => { setLayer("occupation"); setDetail(null); }}>
        Occupation réelle
      </button>
      <button type="button" aria-pressed={layer === "proposed"} onClick={() => { setLayer("proposed"); setDetail(null); }}>
        Plan proposé
      </button>
    </div>
    {loading && <p role="status">Lecture de la chronologie hebdomadaire…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {!loading && snapshot && <>
      <p role="status" className="eligSummary">
        <strong>{snapshot.physical_minutes} minutes physiques déclarées</strong> pour ce parent.
        {" "}Les potentiels par activité ne s'additionnent jamais.
        {" "}{snapshot.calendar_checked ?
          snapshot.verified_free_minutes + " minutes libres après vérification Google et réservations locales." :
          "Temps libre inconnu : Google non vérifié (" + snapshot.calendar_state + ")."}
      </p>
      {snapshot.calendar_error && <p role="status" className="eligWarning">{snapshot.calendar_error}</p>}
      <p className="muted">{snapshot.week_start} · {snapshot.timezone_name} ·
        {" "}réservations locales : {snapshot.local_occupied_minutes} min.
        {" "}L'affichage est une lecture, pas une confirmation de plan.</p>
      {snapshot.potential_minutes.length > 0 && <div className="eligLegend" aria-label="Légende des activités">
        {snapshot.potential_minutes.map((item) =>
          <span key={item.work_type_id} className={colorClass(item.work_type_id)}>
            <i aria-hidden="true" />{label(item.work_type_id)} : {item.minutes} min potentielles
          </span>)}
      </div>}
      <p className="muted">Les barres superposées représentent des choix possibles, pas une capacité supplémentaire.
        {" "}Le contour pointillé et le texte indiquent la priorité, indépendamment de la couleur.</p>
      {layer === "proposed" && <div className="eligProposal">
        <label>Unité à prévisualiser (sans confirmation)
          <select value={taskId} onChange={(event) => { setTaskId(event.target.value); setProposal(null); }}>
            <option value="">Sélectionner une tâche</option>
            {availableTasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}
          </select>
        </label>
        <button type="button" disabled={!taskId || previewBusy} onClick={() => void previewTask()}>
          {previewBusy ? "Calcul…" : "Prévisualiser un placement"}
        </button>
        {!proposal && !proposalError && <p className="muted">Aucun plan prévisualisé. Choisis une tâche
          pour demander un aperçu au moteur Python; rien ne sera réservé.</p>}
        {proposalError && <p role="alert" className="error">{proposalError}</p>}
        {proposal && <p role="status">Aperçu non confirmé · {proposal.suggestions.length} placement(s),
          {" "}{proposal.unplaced.length} unité(s) non placée(s).
          {" "}{proposal.unplaced.map((item) => item.label + " : " + item.reason).join(" ; ")}</p>}
      </div>}
      <div className="eligScroll" role="region" aria-label="Grille graphique des jours" tabIndex={0}>
        <div className="eligPlot">
          {snapshot.days.map((day) => {
            const pieces = snapshot.fragments.filter((item) => item.weekday === day.weekday);
            const options = pieces.flatMap((item) => item.choices.filter((choice) =>
              !workTypeFilter || choice.work_type_id === workTypeFilter)
              .map((choice) => ({ fragment: item, choice })));
            const kinds = Array.from(new Set(options.map((item) => item.choice.work_type_id || "NULL")));
            const occupations = snapshot.occupations.filter((item) => item.weekday === day.weekday &&
              (!workTypeFilter || item.kind === "GOOGLE_VERIFIED" || item.work_type_id === workTypeFilter));
            const proposals = proposal?.suggestions.filter((item) =>
              (item.scope_id || catalog?.compatibility_scope_id) === snapshot.scope_id &&
              (!workTypeFilter || item.work_type_id === workTypeFilter) &&
              Date.parse(item.starts_at) < Date.parse(day.ends_at) &&
              Date.parse(item.ends_at) > Date.parse(day.starts_at)) || [];
            const laneCount = layer === "configuration" ? Math.max(1, kinds.length) :
              layer === "occupation" ? Math.max(1, occupations.length) : Math.max(1, proposals.length);
            const height = laneCount * 34 + 6;
            return <div className="eligDay" key={day.weekday}>
              <div className="eligDayName"><strong>{weekdays[day.weekday]}</strong>
                <small>{day.local_date} · {day.minutes / 60} h</small></div>
              <div className="eligTrackWrap">
                <div className="eligLocalRuler" aria-hidden="true">
                  {day.ticks.map((tick, index) => <span key={index} className={index === 0 ? "first" :
                    index === day.ticks.length - 1 ? "last" : ""}
                    style={{ left: 100 * tick.minute / day.minutes + "%" }}>{tick.label}</span>)}
                </div>
                <div className="eligTrack" style={{ height }}>
                {pieces.map((item, index) => <span key={"physical-" + index}
                  className="eligEnvelope" aria-hidden="true" style={{
                    ...geometry(item.start_minute, item.end_minute, day.minutes),
                  }} />)}
                {layer === "configuration" && options.map(({ fragment, choice }, index) =>
                  <button key={"choice-" + index} type="button"
                    className={"eligBar " + colorClass(choice.work_type_id) +
                      (showPriority && choice.priority_rank !== null ? " eligPriority" : "")}
                    style={{
                      ...geometry(fragment.start_minute, fragment.end_minute, day.minutes),
                      top: kinds.indexOf(choice.work_type_id || "NULL") * 34 + 3,
                    }}
                    onClick={() => showFragment(fragment, choice)}
                    aria-label={label(choice.work_type_id) + " · " + fragment.local_date +
                      " · " + timeLabel(fragment.starts_at, zone) + " à " +
                      timeLabel(fragment.ends_at, zone) +
                      (choice.priority_rank === null ? ", priorité neutre" : ", rang " + choice.priority_rank)}
                    title={label(choice.work_type_id) + " · " + timeLabel(fragment.starts_at, zone) +
                      "–" + timeLabel(fragment.ends_at, zone)}>
                    {label(choice.work_type_id)}{showPriority && choice.priority_rank !== null ?
                      " · P" + choice.priority_rank : ""}
                  </button>)}
                {layer === "occupation" && occupations.map((item, index) =>
                  <button key={"occupation-" + index} type="button"
                    className={"eligBar " + (item.kind === "GOOGLE_VERIFIED" ? "eligGoogle" : "eligLocal")}
                    style={{ ...geometry(item.start_minute, item.end_minute, day.minutes), top: index * 34 + 3 }}
                    onClick={() => showOccupation(item)}
                    aria-label={(item.kind === "GOOGLE_VERIFIED" ? "Google vérifié" : "Réservation locale confirmée") +
                      " · " + timeLabel(item.starts_at, zone) + " à " + timeLabel(item.ends_at, zone)}>
                    {item.kind === "GOOGLE_VERIFIED" ? "Google occupé" : "Local confirmé"}
                  </button>)}
                {layer === "proposed" && proposals.map((item, index) => {
                  const g = clipped(item.starts_at, item.ends_at, day);
                  return g && <button key={"proposal-" + index} type="button"
                    className={"eligBar eligProposed " + colorClass(item.work_type_id)}
                    style={{ ...g, top: index * 34 + 3 }}
                    onClick={() => setDetail({
                      title: item.label, dates: timeLabel(item.starts_at, zone) + " → " + timeLabel(item.ends_at, zone),
                      notes: ["Motif : " + (item.placement_reason || "proposé"),
                        "Rang : " + (item.priority_rank ?? "neutre"),
                        "Sources : " + item.eligibility_sources.join(", "),
                        "Aperçu seulement : non réservé"],
                    })} aria-label={"Placement proposé " + item.label}>{item.label}</button>;
                })}
                </div>
              </div>
            </div>;
          })}
        </div>
      </div>
      {detail && <section className="eligDetail" aria-live="polite">
        <h4>{detail.title}</h4><p>{detail.dates}</p>
        <ul>{detail.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
        {layer === "configuration" && editTargets.map((target, index) =>
          <button key={target.seriesId || target.legacyRuleId || index} type="button"
            onClick={() => setEditorTarget(target)}>
            {target.legacyRuleId ? "Convertir la règle historique " + target.legacyRuleId.slice(0, 8) :
              "Modifier la permission " + target.seriesId?.slice(0, 8)}
          </button>)}
        <button type="button" onClick={() => { setDetail(null); setEditTargets([]);
          setEditorTarget(null); }}>Fermer les détails</button>
      </section>}
      {editorTarget && <EligibilityContextEditor
        key={editorTarget.seriesId || editorTarget.legacyRuleId || editorTarget.workTypeId}
        scopeId={editorTarget.scopeId} workTypeId={editorTarget.workTypeId}
        seriesId={editorTarget.seriesId} legacyRuleId={editorTarget.legacyRuleId}
        selectedDate={editorTarget.selectedDate} zone={zone}
        onClose={() => setEditorTarget(null)}
        onSaved={() => { setEditorTarget(null); setEditTargets([]); setDetail(null);
          setRetry((value) => value + 1); }} />}
      {snapshot.issues.length > 0 && <div className="eligDiagnostics">
        <h4>Diagnostics ({snapshot.issues.length})</h4>
        <ul>{snapshot.issues.map((item, i) =>
          <li key={i}>{item.code} · {timeLabel(item.starts_at, zone)} – {timeLabel(item.ends_at, zone)}
            {" "}· {item.state}</li>)}</ul>
      </div>}
      {snapshot.expansion_issues.length > 0 &&
        <p role="status">Anomalies de dates civiles : {snapshot.expansion_issues.map((v) =>
          v.code + " " + v.original_local_date).join(" ; ")}</p>}
      <details className="eligTable">
        <summary>Vue tabulaire accessible des intervalles et occupations</summary>
        <div className="eligTableScroll"><table><thead><tr><th>Jour</th><th>Instants (offset)</th>
          <th>Type</th><th>Priorité / état</th><th>Source</th></tr></thead><tbody>
          {snapshot.fragments.flatMap((fragment, i) => (fragment.choices.length ? fragment.choices :
            [{ work_type_id: null, priority_rank: null, sources: fragment.sources,
              exclusive: false, legacy_mode: null, source_details: [] }]).filter((choice) =>
            !workTypeFilter || choice.work_type_id === workTypeFilter).map((choice, j) =>
              <tr key={"f-" + i + "-" + j}><td>{fragment.local_date}</td>
                <td>{timeLabel(fragment.starts_at, zone)} – {timeLabel(fragment.ends_at, zone)}</td>
                <td>{fragment.null_residual ? "NULL résiduel" : label(choice.work_type_id)}</td>
                <td>{choice.priority_rank === null ? "Neutre" : "Rang " + choice.priority_rank}
                  {choice.exclusive ? " · historique strict" : ""}</td>
                <td>{choice.sources.join(" ; ")}</td></tr>))}
          {snapshot.occupations.map((item, i) => <tr key={"o-" + i}>
            <td>{item.local_date}</td><td>{timeLabel(item.starts_at, zone)} – {timeLabel(item.ends_at, zone)}</td>
            <td>{item.kind === "GOOGLE_VERIFIED" ? "Google occupé vérifié" : "Local confirmé"}</td>
            <td>Occupé</td><td>{item.source}</td></tr>)}
        </tbody></table></div>
      </details>
    </>}
  </section>;
}
