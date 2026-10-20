import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { apiFetch } from "./auth";
import { EligibilityContextEditor, type EditablePermission, type GridIntent } from "./EligibilityContextEditor";
import type { ScopeCatalog } from "./ScheduleCategories";
import "./weekly-eligibility.css";

type WorkType = { id: string; name: string; scope_id: string };
type TaskChoice = { id: string; title: string; status: string; work_type_id: string | null };
type CivilPart = {
  starts_at: string; ends_at: string; local_date: string; weekday: number;
  start_minute: number; end_minute: number; minutes: number;
};
type Choice = { work_type_id: string | null; priority_rank: number | null };
type Fragment = CivilPart & { scope_id: string; choices: Choice[]; null_residual: boolean };
type Occupation = CivilPart & {
  kind: "LOCAL_CONFIRMED" | "GOOGLE_VERIFIED"; source: string;
  title?: string; work_type_id?: string | null;
};
type Day = {
  weekday: number; local_date: string; starts_at: string; ends_at: string;
  minutes: number; ticks: { label: string; minute: number }[];
};
type Issue = { code: string; starts_at: string; ends_at: string; state: string };
type Snapshot = {
  week_start: string; timezone_name: string; scope_id: string;
  calendar_state: string; calendar_checked: boolean; calendar_error: string | null;
  revision_fingerprint?: string; physical_minutes: number;
  verified_free_minutes: number | null; local_occupied_minutes: number;
  potential_minutes: { work_type_id: string; minutes: number }[];
  days: Day[]; fragments: Fragment[]; editable_permissions?: EditablePermission[];
  occupations: Occupation[]; issues: Issue[];
  expansion_issues: { code: string; original_local_date: string }[];
};
type Proposal = { suggestions: {
  label: string; scope_id: string | null; work_type_id: string | null;
  starts_at: string; ends_at: string; placement_reason: string | null;
}[]; unplaced: { label: string; reason: string }[] };
type Layer = "configuration" | "occupation" | "proposed";
type Selected = { source: EditablePermission | null; workTypeId: string;
  selectedDate: string; intent: GridIntent | null };
type Gesture = {
  pointer: number; kind: "create" | "move" | "start" | "end";
  originDay: number; targetDay: number; anchor: number; initialStart: number;
  initialEnd: number; draftStart: number; draftEnd: number;
  source: EditablePermission | null; moved: boolean;
};
const weekdays = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
const PX_PER_HOUR = 54;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function labelTime(instant: string, zone: string): string {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: zone, hour: "2-digit",
    minute: "2-digit", timeZoneName: "shortOffset" }).format(new Date(instant));
}
function civilTime(day: Day, minute: number, zone: string) {
  if (minute >= day.minutes) return "24:00";
  const instant = new Date(Date.parse(day.starts_at) + minute * 60000);
  return new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit",
    minute: "2-digit", hourCycle: "h23" }).format(instant);
}
function hourMinute(day: Day, hour: number) {
  if (hour === 24) return day.minutes;
  const anchor = Math.floor(hour / 6) * 6;
  const tick = day.ticks.find((t) => t.label === String(anchor).padStart(2, "0") + ":00");
  return (tick?.minute ?? anchor * 60) + (hour - anchor) * 60;
}
function displayBounds(day: Day, from: number, to: number): [number, number] {
  return [hourMinute(day, from), hourMinute(day, to)];
}
function overlap(a: number, b: number, c: number, d: number) {
  return a < d && b > c;
}
async function readApi<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error((typeof body?.detail === "string" ? body.detail : "Lecture refusée") +
      " (" + response.status + ")");
  }
  return response.json() as Promise<T>;
}
function positioned(day: Day, from: number, to: number, top: number, bottom: number) {
  const start = clamp(from, top, bottom), end = clamp(to, top, bottom);
  if (start >= end) return null;
  return { top: 100 * (start - top) / (bottom - top) + "%",
    height: 100 * (end - start) / (bottom - top) + "%" };
}
function minuteOf(day: Day, instant: string) {
  return (Date.parse(instant) - Date.parse(day.starts_at)) / 60000;
}
function assignLanes(day: Day, sources: EditablePermission[]) {
  const items = sources.map((source) => ({
    source, start: minuteOf(day, source.starts_at), end: minuteOf(day, source.ends_at),
  })).filter((item) => overlap(item.start, item.end, 0, day.minutes))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const finishes: number[] = [];
  const placed = items.map((item) => {
    let lane = finishes.findIndex((end) => end <= item.start);
    if (lane < 0) { lane = finishes.length; finishes.push(item.end); }
    else finishes[lane] = item.end;
    return { ...item, lane };
  });
  return { placed, count: Math.max(1, finishes.length) };
}

export function WeeklyEligibilityChart({ week, zone, scopeId, catalog, workTypes, tasks,
  onSelectScope, onSaved, requestNewWindow = 0 }: {
  week: string; zone: string; scopeId: string | null; catalog: ScopeCatalog | null;
  workTypes: WorkType[]; tasks: TaskChoice[]; onSelectScope: (id: string) => void;
  onSaved?: () => void; requestNewWindow?: number;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [layer, setLayer] = useState<Layer>("configuration");
  const [workTypeFilter, setWorkTypeFilter] = useState("");
  const [showPriority, setShowPriority] = useState(true);
  const [startHour, setStartHour] = useState(6);
  const [endHour, setEndHour] = useState(20);
  const [snapSize, setSnapSize] = useState(15);
  const [mobileDay, setMobileDay] = useState(0);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [newType, setNewType] = useState("");
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const canvas = useRef<HTMLDivElement | null>(null);
  const [taskId, setTaskId] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [proposalError, setProposalError] = useState("");
  const [retry, setRetry] = useState(0);
  const eligibleTypes = workTypes.filter((item) => item.scope_id === scopeId);
  const selectedType = newType && eligibleTypes.some((item) => item.id === newType) ?
    newType : eligibleTypes[0]?.id || "";
  const height = Math.max(1, endHour - startHour) * PX_PER_HOUR;

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setSnapshot(null); setSelected(null); setGesture(null);
    setProposal(null);
    if (!scopeId) { setLoading(false); return; }
    const params = new URLSearchParams({ week_start: week, timezone_name: zone, scope_id: scopeId });
    void readApi<Snapshot>("/api/availability/eligibility-week?" + params)
      .then((value) => { if (active) setSnapshot(value); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Grille indisponible.");
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [week, zone, scopeId, retry]);

  useEffect(() => {
    if (requestNewWindow && scopeId) {
      setLayer("configuration");
      setSelected({ source: null, workTypeId: "", selectedDate: week, intent: null });
    }
  }, [requestNewWindow, scopeId, week]);

  function activity(id: string | null) {
    return id === null ? "Résiduel non attribué" :
      workTypes.find((x) => x.id === id)?.name || "Activité " + id.slice(0, 8);
  }
  function color(id: string | null) {
    const n = workTypes.findIndex((x) => x.id === id);
    return "eligColor" + (Math.max(0, n) % 6);
  }
  function chooseSource(source: EditablePermission, initial: GridIntent | null = null,
    date = source.original_local_date) {
    setNotice(""); setSelected({ source, workTypeId: source.work_type_id, selectedDate: date, intent: initial });
  }
  function chooseNew(day: Day, initial: GridIntent | null = null) {
    setNotice("");
    setSelected({ source: null, workTypeId: selectedType, selectedDate: day.local_date, intent: initial });
  }
  function newPermission() {
    if (!snapshot?.days.length) {
      setSelected({ source: null, workTypeId: selectedType, selectedDate: week, intent: null });
      return;
    }
    chooseNew(snapshot.days[mobileDay] || snapshot.days[0]);
  }
  function begin(event: ReactPointerEvent<HTMLElement>, kind: Gesture["kind"],
    day: Day, source: EditablePermission | null) {
    if (event.button !== 0 || layer !== "configuration") return;
    if (source && source.timezone_name !== zone) {
      setNotice("Le fuseau source diffère de la vue : modifier les heures exactes dans le panneau.");
      chooseSource(source); return;
    }
    const [lo, hi] = displayBounds(day, startHour, endHour);
    const rect = event.currentTarget.closest(".eligDayTrack")?.getBoundingClientRect();
    if (!rect) return;
    const clicked = clamp(Math.round(lo + (event.clientY - rect.top) / rect.height * (hi - lo)),
      lo, hi);
    const snap = (v: number) => Math.round(v / snapSize) * snapSize;
    const originStart = source ? minuteOf(day, source.starts_at) : snap(clicked);
    const originEnd = source ? minuteOf(day, source.ends_at) : snap(clicked);
    const start = source ? originStart : clamp(originStart, lo, hi - 1);
    const end = source ? originEnd : Math.min(hi, start + snapSize);
    const g: Gesture = {
      pointer: event.pointerId, kind, originDay: day.weekday, targetDay: day.weekday,
      anchor: clicked, initialStart: start, initialEnd: end,
      draftStart: start, draftEnd: end, source, moved: false,
    };
    canvas.current?.setPointerCapture(event.pointerId);
    setGesture(g); event.preventDefault(); event.stopPropagation();
  }
  function dayFromX(x: number): Day | undefined {
    if (!snapshot || !canvas.current) return;
    const elements = canvas.current.querySelectorAll<HTMLElement>(".eligDayCol");
    for (const element of elements) {
      const r = element.getBoundingClientRect();
      if (x >= r.left && x <= r.right) {
        const index = Number(element.dataset.day);
        return snapshot.days.find((d) => d.weekday === index);
      }
    }
    return snapshot.days.find((d) => d.weekday === mobileDay);
  }
  function moved(event: ReactPointerEvent<HTMLDivElement>) {
    if (!gesture || gesture.pointer !== event.pointerId || !snapshot) return;
    const day = gesture.kind === "move" ? dayFromX(event.clientX) :
      snapshot.days.find((item) => item.weekday === gesture.originDay);
    if (!day) return;
    const element = canvas.current?.querySelector<HTMLElement>(".eligDayCol[data-day='" +
      day.weekday + "'] .eligDayTrack");
    if (!element) return;
    const r = element.getBoundingClientRect(), [lo, hi] = displayBounds(day, startHour, endHour);
    const minute = clamp(lo + (event.clientY - r.top) / r.height * (hi - lo), lo, hi);
    const delta = Math.round((minute - gesture.anchor) / snapSize) * snapSize;
    let start = gesture.initialStart, end = gesture.initialEnd;
    if (gesture.kind === "create") end = clamp(gesture.initialStart + delta, lo, hi);
    if (gesture.kind === "move") {
      const duration = end - start;
      start = clamp(start + delta, lo, hi - duration); end = start + duration;
    }
    if (gesture.kind === "start") start = clamp(start + delta, lo, end - 1);
    if (gesture.kind === "end") end = clamp(end + delta, start + 1, hi);
    // Only pixel offsets are calculated here; no frontend feasibility decision.
    setGesture((before) => before ? ({ ...before, targetDay: day.weekday,
      draftStart: start, draftEnd: end, moved: before.moved || !!delta ||
        day.weekday !== before.originDay }) : before);
  }
  function finish(event: ReactPointerEvent<HTMLDivElement>) {
    if (!gesture || gesture.pointer !== event.pointerId || !snapshot) return;
    if (canvas.current?.hasPointerCapture(event.pointerId))
      canvas.current.releasePointerCapture(event.pointerId);
    const day = snapshot.days.find((d) => d.weekday === gesture.targetDay);
    const source = gesture.source;
    if (day) {
      let lo = gesture.draftStart, hi = gesture.draftEnd;
      if (gesture.kind === "create") {
        if (lo === hi) hi = Math.min(displayBounds(day, startHour, endHour)[1], lo + 60);
        if (lo > hi) [lo, hi] = [hi, lo];
      }
      const unchanged = source && !gesture.moved;
      const startTime = unchanged ? source.starts_at_local :
        civilTime(day, lo, zone);
      const endTime = unchanged ? source.ends_at_local : civilTime(day, hi, zone);
      const startInstant = new Date(Date.parse(day.starts_at) + lo * 60000).toISOString();
      const endInstant = new Date(Date.parse(day.starts_at) + hi * 60000).toISOString();
      const intent: GridIntent = {
        startsAtLocal: startTime, endsAtLocal: endTime,
        daysOfWeek: [day.weekday],
        targetDaysOfWeek: source ? [gesture.originDay] : undefined,
        startsAtInstant: startInstant, endsAtInstant: endInstant,
      };
      if (source) chooseSource(source, unchanged ? null : intent, day.local_date);
      else chooseNew(day, intent);
    }
    setGesture(null);
  }
  async function previewTask() {
    if (!taskId) return;
    setProposalBusy(true); setProposal(null); setProposalError("");
    try {
      const p = await readApi<Proposal>("/api/capacity/weeks/" + week + "/time-blocks/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ task_ids: [taskId], timezone_name: zone }),
      });
      setProposal(p);
    } catch (reason: unknown) {
      setProposalError(reason instanceof Error ? reason.message : "Aperçu indisponible.");
    } finally { setProposalBusy(false); }
  }

  return <section className="availabilityCard eligibilityChart" aria-label="Grille hebdomadaire unifiée">
    <div className="availabilityCardHeading">
      <div><h3>Grille hebdomadaire éditable</h3>
        <p className="muted">Une enveloppe physique par parent; les permissions superposées
          sont des choix, jamais de la capacité supplémentaire.</p></div>
      <button type="button" disabled={loading || !scopeId} onClick={newPermission}>+ Nouvelle plage</button>
    </div>
    <div className="eligControls">
      <label>Parent<select aria-label="Parent de la grille" value={scopeId || ""}
        onChange={(event) => onSelectScope(event.target.value)}>
        <option value="">Choisir un parent</option>
        {catalog?.scopes.filter((scope) => scope.state === "ACTIVE").map((scope) =>
          <option key={scope.id} value={scope.id}>{scope.name}</option>)}
      </select></label>
      <label>Activité<select value={workTypeFilter}
        onChange={(event) => setWorkTypeFilter(event.target.value)}>
        <option value="">Toutes les activités</option>
        {eligibleTypes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label>Début visible<select value={startHour} onChange={(event) => setStartHour(Number(event.target.value))}>
        {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}
          disabled={i >= endHour}>{String(i).padStart(2, "0")}:00</option>)}
      </select></label>
      <label>Fin visible<select value={endHour} onChange={(event) => setEndHour(Number(event.target.value))}>
        {Array.from({ length: 24 }, (_, i) => <option key={i} value={i + 1}
          disabled={i + 1 <= startHour}>{String(i + 1).padStart(2, "0")}:00</option>)}
      </select></label>
      <button type="button" onClick={() => { setStartHour(0); setEndHour(24); }}>Voir 24 h</button>
      <button type="button" onClick={() => { setStartHour(6); setEndHour(20); }}>06–20 h</button>
      <label>Pas de geste<select value={snapSize} onChange={(event) => setSnapSize(Number(event.target.value))}>
        <option value={5}>5 min</option><option value={15}>15 min</option><option value={30}>30 min</option>
      </select></label>
      <label><input type="checkbox" checked={showPriority}
        onChange={(event) => setShowPriority(event.target.checked)} /> Montrer les rangs</label>
      <button type="button" disabled={loading} onClick={() => setRetry((x) => x + 1)}>Actualiser</button>
    </div>
    <div className="eligTabs" role="group" aria-label="Couches de la grille">
      {([["configuration", "Configuration"], ["occupation", "Occupation réelle"],
        ["proposed", "Plan proposé"]] as const).map(([id, text]) =>
        <button key={id} type="button" aria-pressed={layer === id}
          onClick={() => { setLayer(id); setGesture(null); }}>{text}</button>)}
    </div>
    {loading && <p role="status">Lecture de la semaine…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="eligWarning">{notice}</p>}
    {snapshot && !loading && <>
      <p className="eligSummary" role="status"><strong>{snapshot.physical_minutes} minutes physiques</strong>
        {" "}déclarées · {snapshot.local_occupied_minutes} minutes occupées localement.
        {" "}{snapshot.calendar_checked ?
          snapshot.verified_free_minutes + " minutes libres vérifiées." :
          "Google non vérifié (" + snapshot.calendar_state + ") : temps libre inconnu."}
      </p>
      {snapshot.calendar_error && <p className="eligWarning" role="status">{snapshot.calendar_error}</p>}
      <div className="eligLegend" aria-label="Légende de priorité et d'activité">
        {snapshot.potential_minutes.map((item) => <span key={item.work_type_id}
          className={color(item.work_type_id)}>
          <i aria-hidden="true" />{activity(item.work_type_id)} · {item.minutes} min potentielles</span>)}
      </div>
      {layer === "proposed" && <div className="eligProposal">
        <label>Tâche à prévisualiser<select value={taskId}
          onChange={(event) => { setTaskId(event.target.value); setProposal(null); }}>
          <option value="">Choisir une tâche</option>
          {tasks.filter((t) => ["TODO", "IN_PROGRESS"].includes(t.status) && t.work_type_id)
            .map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select></label>
        <button type="button" disabled={!taskId || proposalBusy} onClick={() => void previewTask()}>
          {proposalBusy ? "Calcul…" : "Prévisualiser un placement"}</button>
        {proposalError && <p role="alert" className="error">{proposalError}</p>}
        {proposal && <p role="status">Aperçu non réservé · {proposal.suggestions.length} proposition(s) ·
          {proposal.unplaced.map((x) => x.label + " : " + x.reason).join(" ; ")}</p>}
      </div>}
      <nav className="eligMobileDay" aria-label="Jour visible sur mobile">
        <button type="button" onClick={() => setMobileDay((day) => Math.max(0, day - 1))}
          disabled={mobileDay === 0}>← Jour précédent</button>
        <span>{weekdays[mobileDay]} · {snapshot.days[mobileDay]?.local_date}</span>
        <button type="button" onClick={() => setMobileDay((day) => Math.min(6, day + 1))}
          disabled={mobileDay === 6}>Jour suivant →</button>
      </nav>
      <p className="muted">Cliquer-glisser sur le fond pour créer, glisser une barre pour déplacer,
        ou saisir sa poignée pour redimensionner. Au clavier/tactile, sélectionner une barre
        puis modifier ses heures dans le panneau. Aucun geste ne confirme une écriture.</p>
      <div className="eligVScroll" role="region" aria-label="Grille des sept jours, heures verticales" tabIndex={0}>
        <div ref={canvas} className="eligGridCanvas" onPointerMove={moved} onPointerUp={finish}
          onPointerCancel={() => setGesture(null)}>
          <div className="eligHourRuler" aria-hidden="true">
            <div className="eligColumnHead">Heure</div>
            <div className="eligRulerTrack" style={{ height }}>
              {Array.from({ length: endHour - startHour + 1 }, (_, index) =>
                <span key={index} style={{ top: 100 * index / (endHour - startHour) + "%" }}>
                  {String(startHour + index).padStart(2, "0")}:00</span>)}
            </div>
          </div>
          {snapshot.days.map((day) => {
            const [lo, hi] = displayBounds(day, startHour, endHour);
            const sources = (snapshot.editable_permissions || []).filter((item) =>
              (!workTypeFilter || item.work_type_id === workTypeFilter));
            const lanes = assignLanes(day, sources);
            const occupations = snapshot.occupations.filter((item) =>
              (!workTypeFilter || !item.work_type_id || item.work_type_id === workTypeFilter) &&
              overlap(minuteOf(day, item.starts_at), minuteOf(day, item.ends_at), 0, day.minutes));
            const suggestions = proposal?.suggestions.filter((item) => item.scope_id === scopeId &&
              (!workTypeFilter || item.work_type_id === workTypeFilter) &&
              overlap(minuteOf(day, item.starts_at), minuteOf(day, item.ends_at), 0, day.minutes)) || [];
            const ghost = gesture && gesture.targetDay === day.weekday ?
              positioned(day, Math.min(gesture.draftStart, gesture.draftEnd),
                Math.max(gesture.draftStart, gesture.draftEnd), lo, hi) : null;
            return <div key={day.local_date} className={"eligDayCol" +
              (mobileDay === day.weekday ? " eligVisibleDay" : "")} data-day={day.weekday}>
              <div className="eligColumnHead"><strong>{weekdays[day.weekday]}</strong>
                <small>{day.local_date} · {day.minutes / 60} h</small></div>
              <div className="eligDayTrack" style={{ height }}
                aria-label={weekdays[day.weekday] + " " + day.local_date + ", choisir une plage vide"}
                onPointerDown={(event) => begin(event, "create", day, null)}>
                {Array.from({ length: endHour - startHour + 1 }, (_, index) =>
                  <span key={index} className="eligHourLine" aria-hidden="true"
                    style={{ top: 100 * index / (endHour - startHour) + "%" }} />)}
                {snapshot.fragments.filter((f) => f.weekday === day.weekday).map((fragment, index) => {
                  const position = positioned(day, fragment.start_minute, fragment.end_minute, lo, hi);
                  return position && <span key={index} className="eligPhysical" style={position}
                    aria-hidden="true" />;
                })}
                {layer === "configuration" && lanes.placed.map(({ source, start, end, lane }) => {
                  const position = positioned(day, start, end, lo, hi);
                  if (!position) return null;
                  const laneWidth = 100 / lanes.count;
                  const title = activity(source.work_type_id) + " · " +
                    labelTime(source.starts_at, zone) + " à " + labelTime(source.ends_at, zone) +
                    (source.priority_rank === null ? " · rang neutre" : " · rang " + source.priority_rank);
                  return <div key={source.series_id + ":" + source.original_local_date + ":" + source.revision}
                    className={"eligPermission " + color(source.work_type_id) +
                      (showPriority && source.priority_rank !== null ? " eligPriority" : "")}
                    style={{ ...position, left: lane * laneWidth + "%", width: laneWidth + "%" }}>
                    <button type="button" className="eligVHandle eligStartHandle"
                      aria-label={"Modifier le début : " + title}
                      onPointerDown={(event) => begin(event, "start", day, source)}
                      onClick={() => chooseSource(source)} />
                    <button type="button" className="eligVBar" title={title} aria-label={title}
                      onPointerDown={(event) => begin(event, "move", day, source)}
                      onClick={(event) => { if (event.detail === 0) chooseSource(source); }}>
                      {activity(source.work_type_id)}
                      {showPriority && source.priority_rank !== null ? " · P" + source.priority_rank : ""}
                    </button>
                    <button type="button" className="eligVHandle eligEndHandle"
                      aria-label={"Modifier la fin : " + title}
                      onPointerDown={(event) => begin(event, "end", day, source)}
                      onClick={() => chooseSource(source)} />
                  </div>;
                })}
                {layer === "occupation" && occupations.map((item, index) => {
                  const position = positioned(day, minuteOf(day, item.starts_at),
                    minuteOf(day, item.ends_at), lo, hi);
                  return position && <div key={index}
                    className={"eligOccupation " + (item.kind === "GOOGLE_VERIFIED" ? "eligGoogle" : "eligLocal")}
                    style={{ ...position, left: (index % 3) * 33.33 + "%", width: "33.33%" }}
                    title={item.title || item.source} tabIndex={0}
                    aria-label={(item.kind === "GOOGLE_VERIFIED" ? "Google occupé" : "Réservation confirmée") +
                      " : " + labelTime(item.starts_at, zone) + " – " + labelTime(item.ends_at, zone)}>
                    {item.kind === "GOOGLE_VERIFIED" ? "Google" : "Confirmé"}</div>;
                })}
                {layer === "proposed" && suggestions.map((item, index) => {
                  const position = positioned(day, minuteOf(day, item.starts_at),
                    minuteOf(day, item.ends_at), lo, hi);
                  return position && <div key={index} className="eligPlanned" style={position}
                    title={item.placement_reason || "Aperçu non confirmé"}>{item.label}</div>;
                })}
                {ghost && layer === "configuration" && <span className="eligGhost" style={ghost}
                  aria-label="Brouillon visuel non confirmé" />}
              </div>
            </div>;
          })}
        </div>
      </div>
      {layer === "configuration" && !snapshot.editable_permissions?.length &&
        <p className="eligWarning" role="status">Aucune permission pour cette semaine.
          Choisir « + Nouvelle plage » ou sélectionner un intervalle vide.
          Commencer par créer un parent, une sous-catégorie et une enveloppe si nécessaire.</p>}
      {selected && layer === "configuration" && <div className="eligContextPanel">
        {!selected.source && <label>Activité de la nouvelle permission
          <select value={selected.workTypeId || selectedType} onChange={(event) =>
            setSelected((prev) => prev && ({ ...prev, workTypeId: event.target.value }))}>
            {eligibleTypes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></label>}
        {!eligibleTypes.length && <p role="alert">Ajouter d'abord une sous-catégorie à ce parent.</p>}
        {!!(selected.workTypeId || selectedType) && <EligibilityContextEditor
          key={(selected.source?.series_id || "new") + ":" + selected.selectedDate +
            ":" + (selected.intent?.startsAtLocal || "") + ":" + selected.workTypeId}
          scopeId={scopeId || ""} workTypeId={selected.workTypeId || selectedType}
          zone={zone} seriesId={selected.source?.series_id || null}
          selectedDate={selected.selectedDate} source={selected.source} initial={selected.intent}
          onClose={() => setSelected(null)}
          onSaved={() => { setSelected(null); setRetry((n) => n + 1); onSaved?.(); }} />}
      </div>}
      {!!snapshot.issues.length && <div className="eligDiagnostics">
        <h4>Conflits ({snapshot.issues.length})</h4>
        <ul>{snapshot.issues.map((issue, i) => <li key={i}>{issue.code} ·
          {labelTime(issue.starts_at, zone)} – {labelTime(issue.ends_at, zone)} · {issue.state}</li>)}</ul>
      </div>}
      {!!snapshot.expansion_issues.length && <p role="status" className="eligWarning">
        DST : {snapshot.expansion_issues.map((x) => x.code + " le " + x.original_local_date).join("; ")}</p>}
      <details className="eligTable"><summary>Liste accessible des permissions et occupations</summary>
        <div className="eligTableScroll"><table><thead><tr>
          <th>Jour</th><th>Source / activité</th><th>Heures (offset explicite)</th><th>Rang</th><th>Action</th>
        </tr></thead><tbody>
          {(snapshot.editable_permissions || []).filter((p) => !workTypeFilter ||
            p.work_type_id === workTypeFilter).map((p, i) =>
            <tr key={p.series_id + ":" + i}><td>{p.original_local_date}</td>
              <td>{activity(p.work_type_id)} · révision {p.revision}</td>
              <td>{labelTime(p.starts_at, zone)} – {labelTime(p.ends_at, zone)}</td>
              <td>{p.priority_rank ?? "neutre"}</td>
              <td><button type="button" onClick={() => { setLayer("configuration"); chooseSource(p); }}>
                Modifier sans glisser</button></td></tr>)}
          {snapshot.occupations.map((o, i) => <tr key={"occup-" + i}>
            <td>{o.local_date}</td><td>{o.kind === "GOOGLE_VERIFIED" ? "Google occupé" : "Local confirmé"}</td>
            <td>{labelTime(o.starts_at, zone)} – {labelTime(o.ends_at, zone)}</td>
            <td>Occupé</td><td>Lecture seule</td></tr>)}
        </tbody></table></div>
      </details>
    </>}
  </section>;
}
