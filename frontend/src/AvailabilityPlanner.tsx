import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "./auth";
import "./availability.css";

type WorkType = { id: string; name: string };
type Mode = "PROTECTED" | "PREFERRED";
type Kind = "GENERAL" | "CATEGORIZED";
type Action = "CANCEL" | "REPLACE" | "ADD" | "UNAVAILABLE";
type Revision = {
  number: number; effective_from: string; valid_until: string | null;
  timezone_name: string; days_of_week: number[]; starts_at_local: string;
  ends_at_local: string; kind: Kind; work_type_id: string | null;
  mode: Mode | null; enabled: boolean; start_fold: number | null; end_fold: number | null;
};
type Rule = { id: string; version: number; revisions: Revision[] };
type Occurrence = {
  rule_id: string; revision: number; original_local_date: string;
  starts_at: string; ends_at: string; work_type_id: string | null;
  kind: Kind; mode: Mode | null;
};
type ProjectionIssue = {
  code: string; starts_at: string; ends_at: string; sources: string[];
  booking_id: string | null; state: string | null;
};
type Projection = {
  projection: string; declared_minutes: number;
  blocks: { id: string; starts_at: string; ends_at: string; work_type_id: string | null;
    mode: Mode | null; sources: string[]; minutes: number }[];
  issues: ProjectionIssue[];
  expansion_issues: { rule_id: string; revision: number; original_local_date: string; reason: string }[];
};
type Exception = {
  id: string; version: number; action: Action; rule_id: string | null;
  original_local_date: string | null; starts_at: string | null; ends_at: string | null;
  timezone_name: string; kind: Kind | null; work_type_id: string | null;
  mode: Mode | null; enabled: boolean; reason: string | null;
};
type Booking = {
  id: string; task_id: string; work_type_id: string | null; starts_at: string;
  ends_at: string; status: string; revision: number;
};
type Verified = {
  calendar_checked: boolean; declared_minutes: number; free_minutes: number;
  by_work_type: { work_type_id: string | null; declared_minutes: number; free_minutes: number }[];
  issues: ProjectionIssue[];
};
type ResolutionDecision = "CANCEL" | "MOVE" | "KEEP";
type ResolutionPreview = {
  fingerprint: string; decision: ResolutionDecision; conflict_codes: string[];
  calendar_checked: boolean; consequences: string[];
  replacement: { starts_at: string; ends_at: string } | null;
};
type ExceptionPreview = Projection & { fingerprint: string; from: string; to: string };

const headers = { "Content-Type": "application/json" };
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const weekdays = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const initialRule = {
  effective_from: "", valid_until: "", timezone_name: browserZone,
  days_of_week: [0, 1, 2, 3, 4] as number[], starts_at_local: "09:00",
  ends_at_local: "17:00", kind: "GENERAL" as Kind, work_type_id: "",
  mode: "PREFERRED" as Mode, enabled: true, start_fold: "", end_fold: "",
};
const initialException = {
  action: "UNAVAILABLE" as Action, rule_id: "", original_local_date: "",
  starts_at: "", ends_at: "", timezone_name: browserZone,
  kind: "GENERAL" as Kind, work_type_id: "", mode: "PREFERRED" as Mode,
  enabled: true, reason: "",
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = typeof data?.detail === "string" ? data.detail :
      response.status === 409 ? "Les données ont changé. Actualise et recommence l'aperçu." :
      "Opération refusée (" + response.status + ").";
    throw new Error(detail);
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
}

function dateISO(date: Date): string {
  return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")].join("-");
}
function weekOf(value: string): string {
  const date = new Date(value + "T12:00:00");
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  return dateISO(date);
}
function shiftDay(value: string, days: number): string {
  const date = new Date(value + "T12:00:00");
  date.setDate(date.getDate() + days);
  return dateISO(date);
}
function dayInZone(value: string, zone: string): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: zone, year: "numeric",
    month: "2-digit", day: "2-digit" }).format(new Date(value));
}
function timeInZone(value: string, zone: string): string {
  return new Intl.DateTimeFormat("fr-CA", { timeZone: zone, hour: "2-digit",
    minute: "2-digit", hour12: false }).format(new Date(value));
}
function stamp(value: string): string {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) throw new Error("Date et heure invalides.");
  const offset = -date.getTimezoneOffset();
  const sign = offset < 0 ? "-" : "+";
  const absolute = Math.abs(offset);
  return value + ":00" + sign + String(Math.floor(absolute / 60)).padStart(2, "0") +
    ":" + String(absolute % 60).padStart(2, "0");
}
function weekQuery(start: string, zone: string): string {
  return "?from=" + start + "&to=" + shiftDay(start, 7) +
    "&timezone_name=" + encodeURIComponent(zone);
}
function shortId(id: string): string { return id.slice(0, 8); }

export function AvailabilityPlanner({ workTypes }: { workTypes: WorkType[] }) {
  const [tab, setTab] = useState<"rules" | "real">("rules");
  const [week, setWeek] = useState(() => weekOf(dateISO(new Date())));
  const [zone, setZone] = useState(browserZone);
  const [rules, setRules] = useState<Rule[]>([]);
  const [occurrences, setOccurrences] = useState<Occurrence[]>([]);
  const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [verified, setVerified] = useState<Verified | null>(null);
  const [verifiedError, setVerifiedError] = useState("");
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [ruleDraft, setRuleDraft] = useState(initialRule);
  const [editingRule, setEditingRule] = useState<Rule | null>(null);
  const [exceptionDraft, setExceptionDraft] = useState(initialException);
  const [editingException, setEditingException] = useState<Exception | null>(null);
  const [exceptionPreview, setExceptionPreview] = useState<{
    snapshot: ExceptionPreview; payload: object; version: number | null; id: string | null;
  } | null>(null);
  const [resolutionId, setResolutionId] = useState("");
  const [resolutionDecision, setResolutionDecision] = useState<ResolutionDecision>("KEEP");
  const [resolutionReason, setResolutionReason] = useState("");
  const [moveStart, setMoveStart] = useState("");
  const [moveEnd, setMoveEnd] = useState("");
  const [resolutionPreview, setResolutionPreview] = useState<{
    bookingId: string; payload: object; snapshot: ResolutionPreview;
  } | null>(null);
  const [history, setHistory] = useState<{ event_type: string; occurred_at: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const label = (id: string | null) =>
    id ? workTypes.find((type) => type.id === id)?.name || "Type " + shortId(id) : "Non classé (NULL)";
  const describe = (start: string, end: string) =>
    dayInZone(start, zone) + " " + timeInZone(start, zone) + " – " +
    dayInZone(end, zone) + " " + timeInZone(end, zone);

  const reload = useCallback(async () => {
    const query = weekQuery(week, zone);
    const [nextRules, nextOccurrences, nextExceptions, nextProjection, nextBookings] =
      await Promise.all([
        api<Rule[]>("/api/availability/rules"),
        api<{ occurrences: Occurrence[] }>("/api/availability/rules/occurrences?from=" +
          week + "&to=" + shiftDay(week, 7)),
        api<Exception[]>("/api/availability/exceptions"),
        api<Projection>("/api/availability/effective" + query),
        api<Booking[]>("/api/capacity/weeks/" + week + "/time-blocks"),
      ]);
    setRules(nextRules); setOccurrences(nextOccurrences.occurrences);
    setExceptions(nextExceptions); setProjection(nextProjection); setBookings(nextBookings);
  }, [week, zone]);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setVerified(null); setVerifiedError("");
    setExceptionPreview(null); setResolutionPreview(null);
    void reload().catch((err: unknown) => {
      if (active) setError(err instanceof Error ? err.message : "Lecture impossible.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);

  async function operate(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      await reload();
      setVerified(null);
      setNotice(success);
    } catch (err: unknown) {
      setExceptionPreview(null); setResolutionPreview(null);
      setError(err instanceof Error ? err.message : "Opération impossible.");
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  function rulePayload() {
    return {
      ...ruleDraft,
      valid_until: ruleDraft.valid_until || null,
      work_type_id: ruleDraft.kind === "CATEGORIZED" ? ruleDraft.work_type_id || null : null,
      mode: ruleDraft.kind === "CATEGORIZED" ? ruleDraft.mode : null,
      start_fold: ruleDraft.start_fold === "" ? null : Number(ruleDraft.start_fold),
      end_fold: ruleDraft.end_fold === "" ? null : Number(ruleDraft.end_fold),
    };
  }
  async function saveRule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ruleDraft.days_of_week.length) { setError("Sélectionne au moins un jour."); return; }
    if (editingRule && !window.confirm("Réviser uniquement les occurrences futures dès la date d'effet ? Le passé est conservé.")) return;
    await operate(async () => {
      const body = editingRule ? { ...rulePayload(), expected_version: editingRule.version } : rulePayload();
      await api<Rule>("/api/availability/rules" + (editingRule ? "/" + editingRule.id : ""), {
        method: editingRule ? "PATCH" : "POST", headers, body: JSON.stringify(body),
      });
      setEditingRule(null); setRuleDraft(initialRule);
    }, "Horaire habituel enregistré.");
  }
  function editRule(rule: Rule) {
    const revision = rule.revisions[rule.revisions.length - 1];
    setEditingRule(rule);
    setRuleDraft({
      effective_from: shiftDay(week, 7), valid_until: revision.valid_until || "",
      timezone_name: revision.timezone_name, days_of_week: [...revision.days_of_week],
      starts_at_local: revision.starts_at_local, ends_at_local: revision.ends_at_local,
      kind: revision.kind, work_type_id: revision.work_type_id || "",
      mode: revision.mode || "PREFERRED", enabled: revision.enabled,
      start_fold: revision.start_fold === null ? "" : String(revision.start_fold),
      end_fold: revision.end_fold === null ? "" : String(revision.end_fold),
    });
    setTab("rules");
  }
  async function disableRule(rule: Rule) {
    const effective = window.prompt("Désactiver à partir de la date (AAAA-MM-JJ, futur uniquement) :", shiftDay(week, 7));
    if (!effective || !window.confirm("Désactiver les occurrences futures sans effacer l'historique ?")) return;
    await operate(async () => {
      await api<void>("/api/availability/rules/" + rule.id + "?expected_version=" +
        rule.version + "&effective_from=" + encodeURIComponent(effective), { method: "DELETE" });
    }, "Règle désactivée pour le futur.");
  }

  function updateException(patch: Partial<typeof initialException>) {
    setExceptionDraft((current) => ({ ...current, ...patch }));
    setExceptionPreview(null);
  }
  function chooseOccurrence(occurrence: Occurrence, action: "CANCEL" | "REPLACE") {
    setEditingException(null);
    setExceptionDraft({
      ...initialException, action, rule_id: occurrence.rule_id,
      original_local_date: occurrence.original_local_date, timezone_name: zone,
      kind: occurrence.kind, work_type_id: occurrence.work_type_id || "",
      mode: occurrence.mode || "PREFERRED",
    });
    setExceptionPreview(null); setTab("real");
  }
  function editException(value: Exception) {
    setEditingException(value); setExceptionPreview(null);
    setExceptionDraft({
      action: value.action, rule_id: value.rule_id || "",
      original_local_date: value.original_local_date || "",
      starts_at: value.starts_at ? dayInZone(value.starts_at, value.timezone_name) + "T" +
        timeInZone(value.starts_at, value.timezone_name) : "",
      ends_at: value.ends_at ? dayInZone(value.ends_at, value.timezone_name) + "T" +
        timeInZone(value.ends_at, value.timezone_name) : "",
      timezone_name: value.timezone_name, kind: value.kind || "GENERAL",
      work_type_id: value.work_type_id || "", mode: value.mode || "PREFERRED",
      enabled: value.enabled, reason: value.reason || "",
    });
    setTab("real");
  }
  function exceptionPayload() {
    const action = exceptionDraft.action;
    if (action !== "CANCEL" && exceptionDraft.timezone_name !== browserZone) {
      throw new Error("Pour saisir une heure, le fuseau du navigateur doit correspondre au fuseau sélectionné. La lecture reste disponible.");
    }
    return {
      action,
      rule_id: action === "CANCEL" || action === "REPLACE" ? exceptionDraft.rule_id || null : null,
      original_local_date: action === "CANCEL" || action === "REPLACE" ?
        exceptionDraft.original_local_date || null : null,
      starts_at: action === "CANCEL" ? null : stamp(exceptionDraft.starts_at),
      ends_at: action === "CANCEL" ? null : stamp(exceptionDraft.ends_at),
      timezone_name: exceptionDraft.timezone_name,
      kind: action === "UNAVAILABLE" || action === "CANCEL" ? null : exceptionDraft.kind,
      work_type_id: action === "ADD" || action === "REPLACE" ?
        exceptionDraft.kind === "CATEGORIZED" ? exceptionDraft.work_type_id || null : null : null,
      mode: action === "ADD" || action === "REPLACE" ?
        exceptionDraft.kind === "CATEGORIZED" ? exceptionDraft.mode : null : null,
      enabled: exceptionDraft.enabled, reason: exceptionDraft.reason.trim() || null,
    };
  }
  async function previewException(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setExceptionPreview(null);
    try {
      const payload = exceptionPayload();
      const version = editingException?.version ?? null;
      const result = await api<ExceptionPreview>("/api/availability/exceptions/preview", {
        method: "POST", headers, body: JSON.stringify({
          ...payload, exception_id: editingException?.id || null, expected_version: version,
        }),
      });
      setExceptionPreview({ snapshot: result, payload, version, id: editingException?.id || null });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Aperçu impossible."); }
    finally { setBusy(false); }
  }
  async function applyException() {
    if (!exceptionPreview || !window.confirm("Appliquer cette dérogation après examen des conflits ? Aucune réservation n'est déplacée automatiquement.")) return;
    const draft = exceptionPreview;
    await operate(async () => {
      await api<Exception>("/api/availability/exceptions" + (draft.id ? "/" + draft.id : ""), {
        method: draft.id ? "PATCH" : "POST", headers,
        body: JSON.stringify({
          ...draft.payload, expected_version: draft.version,
          expected_fingerprint: draft.snapshot.fingerprint,
          acknowledge_conflicts: draft.snapshot.issues.some((issue) => issue.booking_id !== null),
        }),
      });
      setEditingException(null); setExceptionDraft(initialException); setExceptionPreview(null);
    }, "Dérogation confirmée. Les réservations en conflit restent inchangées.");
  }

  async function loadVerified() {
    setVerified(null); setVerifiedError("");
    try {
      setVerified(await api<Verified>("/api/availability/verified?week_start=" +
        week + "&timezone_name=" + encodeURIComponent(zone)));
    } catch (err: unknown) {
      setVerifiedError((err instanceof Error ? err.message : "Vérification indisponible.") +
        " La capacité déclarée n'est pas du temps libre confirmé.");
    }
  }

  const activeIssues = [...(projection?.issues || []), ...(verified?.issues || [])]
    .filter((issue, index, source) => issue.booking_id && issue.state === "OPEN" &&
      source.findIndex((other) => other.booking_id === issue.booking_id &&
        other.code === issue.code && other.starts_at === issue.starts_at) === index);
  const conflictBookings = bookings.filter((booking) =>
    activeIssues.some((issue) => issue.booking_id === booking.id));
  const selectedBooking = conflictBookings.find((booking) => booking.id === resolutionId);
  function resolutionPayload(booking: Booking) {
    if (resolutionDecision === "MOVE" && zone !== browserZone) {
      throw new Error("Le fuseau horaire de saisie doit correspondre à celui du navigateur.");
    }
    return {
      decision: resolutionDecision, expected_revision: booking.revision,
      timezone_name: zone, reason: resolutionReason.trim(),
      ...(resolutionDecision === "MOVE" ? {
        starts_at: stamp(moveStart), ends_at: stamp(moveEnd),
      } : {}),
    };
  }
  async function previewResolution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedBooking) return;
    setBusy(true); setError(""); setResolutionPreview(null);
    try {
      const payload = resolutionPayload(selectedBooking);
      const snapshot = await api<ResolutionPreview>("/api/capacity/weeks/" + week +
        "/time-blocks/" + selectedBooking.id + "/resolution/preview", {
        method: "POST", headers, body: JSON.stringify(payload),
      });
      setResolutionPreview({ bookingId: selectedBooking.id, payload, snapshot });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Aperçu de résolution impossible."); }
    finally { setBusy(false); }
  }
  async function confirmResolution() {
    if (!resolutionPreview || !window.confirm("Confirmer cette décision locale et son audit ?")) return;
    const draft = resolutionPreview;
    await operate(async () => {
      await api("/api/capacity/weeks/" + week + "/time-blocks/" +
        draft.bookingId + "/resolution/confirm", {
        method: "POST", headers,
        body: JSON.stringify({
          ...draft.payload, fingerprint: draft.snapshot.fingerprint,
          decision_id: crypto.randomUUID(), confirmed: true,
        }),
      });
      setResolutionPreview(null); setResolutionId(""); setResolutionReason(""); setHistory([]);
    }, "Décision enregistrée localement, sans écriture Google Calendar.");
  }
  async function showHistory(bookingId: string) {
    setError("");
    try {
      setHistory(await api<{ event_type: string; occurred_at: string }[]>(
        "/api/capacity/weeks/" + week + "/time-blocks/" + bookingId + "/resolution/history"));
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Historique indisponible."); }
  }

  return (
    <section className="availabilityPanel" aria-label="Disponibilités">
      <div className="availabilityHead">
        <div><h2>Disponibilités</h2><p>Définis une fois ton horaire, puis ajuste les exceptions de la semaine.</p></div>
        <div className="availabilitySwitch" role="group" aria-label="Vue des disponibilités">
          <button type="button" aria-pressed={tab === "rules"} className={tab === "rules" ? "selected" : ""}
            onClick={() => setTab("rules")}>Horaire habituel</button>
          <button type="button" aria-pressed={tab === "real"} className={tab === "real" ? "selected" : ""}
            onClick={() => setTab("real")}>Semaine réelle</button>
        </div>
      </div>
      <div className="availabilityToolbar">
        <label>Semaine du lundi
          <input type="date" value={week} onChange={(event) => setWeek(weekOf(event.target.value || week))} />
        </label>
        <button type="button" onClick={() => setWeek(shiftDay(week, -7))} aria-label="Semaine précédente">←</button>
        <button type="button" onClick={() => setWeek(shiftDay(week, 7))} aria-label="Semaine suivante">→</button>
        <label>Fuseau de lecture
          <input value={zone} onChange={(event) => setZone(event.target.value)} aria-label="Fuseau horaire IANA" />
        </label>
        <button type="button" onClick={() => void reload().catch((err: unknown) =>
          setError(err instanceof Error ? err.message : "Actualisation impossible."))}>Actualiser</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="availabilityNotice">{notice}</p>}
      {loading ? <p role="status">Chargement des disponibilités…</p> : tab === "rules" ? (
        <div className="availabilityStack">
          <section className="availabilityCard">
            <h3>Règles hebdomadaires</h3>
            <p className="muted">Une enveloppe générale et des plages de travail catégorisées ne s'additionnent pas. Protégée interdit le placement ordinaire d'un autre type; préférentielle permet seulement une proposition motivée.</p>
            {rules.length === 0 ? <p className="empty">Aucune règle habituelle. Commence par une enveloppe générale.</p> : (
              <ul className="availabilityRows">{rules.map((rule) => {
                const latest = rule.revisions[rule.revisions.length - 1];
                return <li key={rule.id}>
                  <div><strong>{latest.kind === "GENERAL" ? "Enveloppe générale" : label(latest.work_type_id)}</strong>
                    <span className={"availabilityMode " + (latest.mode || "GENERAL")}>
                      {latest.kind === "GENERAL" ? "Générale" : latest.mode === "PROTECTED" ? "Protégée" : "Préférentielle"}
                    </span>
                    <p>{latest.days_of_week.map((day) => weekdays[day]).join(", ")} · {latest.starts_at_local}–{latest.ends_at_local} · {latest.timezone_name}</p>
                    <small>{latest.enabled ? "Active" : "Désactivée"} dès {latest.effective_from} · version {rule.version} · {rule.revisions.length} révision(s)</small>
                  </div>
                  <div className="availabilityActions">
                    <button type="button" disabled={busy} onClick={() => editRule(rule)}>Réviser</button>
                    {latest.enabled && <button type="button" disabled={busy} onClick={() => void disableRule(rule)}>Désactiver</button>}
                  </div>
                </li>;
              })}</ul>
            )}
          </section>
          <section className="availabilityCard">
            <h3>{editingRule ? "Réviser une série" : "Nouvelle plage récurrente"}</h3>
            <p className="muted">{editingRule ?
              "Une révision s'applique dès sa date future, sans réécrire le passé. Les éditions de série potentiellement incompatibles seront refusées par le serveur." :
              "Pour plusieurs intervalles dans une journée, crée plusieurs règles."}</p>
            <form onSubmit={(event) => void saveRule(event)} className="availabilityForm">
              <div className="availabilityFields">
                <label>Date d'effet<input type="date" required value={ruleDraft.effective_from}
                  onChange={(event) => setRuleDraft({ ...ruleDraft, effective_from: event.target.value })} /></label>
                <label>Jusqu'au (exclusif)<input type="date" value={ruleDraft.valid_until}
                  onChange={(event) => setRuleDraft({ ...ruleDraft, valid_until: event.target.value })} /></label>
                <label>Fuseau IANA<input required value={ruleDraft.timezone_name}
                  onChange={(event) => setRuleDraft({ ...ruleDraft, timezone_name: event.target.value })} /></label>
                <label>Début<input type="time" required value={ruleDraft.starts_at_local}
                  onChange={(event) => setRuleDraft({ ...ruleDraft, starts_at_local: event.target.value })} /></label>
                <label>Fin<input type="time" required value={ruleDraft.ends_at_local}
                  onChange={(event) => setRuleDraft({ ...ruleDraft, ends_at_local: event.target.value })} /></label>
                <label>Nature<select value={ruleDraft.kind} onChange={(event) =>
                  setRuleDraft({ ...ruleDraft, kind: event.target.value as Kind })}>
                  <option value="GENERAL">Enveloppe générale</option><option value="CATEGORIZED">Plage par type</option>
                </select></label>
                {ruleDraft.kind === "CATEGORIZED" && <>
                  <label>Type de travail<select required value={ruleDraft.work_type_id} onChange={(event) =>
                    setRuleDraft({ ...ruleDraft, work_type_id: event.target.value })}>
                    <option value="">Choisir…</option>
                    {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                  </select></label>
                  <label>Protection de la plage<select value={ruleDraft.mode} onChange={(event) =>
                    setRuleDraft({ ...ruleDraft, mode: event.target.value as Mode })}>
                    <option value="PREFERRED">Préférentielle</option><option value="PROTECTED">Protégée</option>
                  </select></label>
                </>}
                <label>Début DST (fold)<select value={ruleDraft.start_fold} onChange={(event) =>
                  setRuleDraft({ ...ruleDraft, start_fold: event.target.value })}>
                  <option value="">Automatique</option><option value="0">Premier instant</option><option value="1">Second instant</option>
                </select></label>
                <label>Fin DST (fold)<select value={ruleDraft.end_fold} onChange={(event) =>
                  setRuleDraft({ ...ruleDraft, end_fold: event.target.value })}>
                  <option value="">Automatique</option><option value="0">Premier instant</option><option value="1">Second instant</option>
                </select></label>
              </div>
              <fieldset className="availabilityDays"><legend>Répéter chaque</legend>
                {weekdays.map((day, index) => <label key={day}>
                  <input type="checkbox" checked={ruleDraft.days_of_week.includes(index)}
                    onChange={(event) => setRuleDraft({ ...ruleDraft, days_of_week: event.target.checked ?
                      [...ruleDraft.days_of_week, index].sort() :
                      ruleDraft.days_of_week.filter((value) => value !== index) })} />{day}
                </label>)}
              </fieldset>
              <div className="availabilityActions"><button disabled={busy}> {editingRule ? "Enregistrer la révision future" : "Créer la règle"}</button>
                {editingRule && <button type="button" onClick={() => { setEditingRule(null); setRuleDraft(initialRule); }}>Annuler</button>}</div>
            </form>
          </section>
        </div>
      ) : (
        <div className="availabilityStack">
          <section className="availabilityCard">
            <div className="availabilityCardHeading"><h3>Semaine du {week}</h3>
              <button type="button" disabled={busy} onClick={() => void loadVerified()}>Vérifier avec Google Calendar</button></div>
            <p><strong>{projection?.declared_minutes ?? 0} minutes déclarées</strong> (projection, pas du temps libre garanti).</p>
            {verified && <p role="status"><strong>{verified.free_minutes} minutes libres vérifiées</strong> sur {verified.declared_minutes} déclarées.
              {verified.by_work_type.map((row) => <span key={row.work_type_id || "null"} className="availabilityBucket">
                {label(row.work_type_id)} : {row.free_minutes}/{row.declared_minutes} min
              </span>)}</p>}
            {verifiedError && <p role="alert" className="error">{verifiedError}</p>}
            <div className="availabilityWeekGrid" aria-label="Grille hebdomadaire réelle">
              {weekdays.map((day, index) => {
                const date = shiftDay(week, index);
                const blocks = projection?.blocks.filter((block) => dayInZone(block.starts_at, zone) === date) || [];
                return <div className="availabilityDay" key={date}>
                  <h4>{day} <small>{date.slice(5)}</small></h4>
                  {blocks.length === 0 ? <p className="empty">Aucune plage</p> :
                    blocks.map((block) => <div className={"availabilitySlot " + (block.mode || "GENERAL")} key={block.id}>
                      <strong>{timeInZone(block.starts_at, zone)}–{timeInZone(block.ends_at, zone)}</strong>
                      <span>{label(block.work_type_id)}</span>
                      <small>{block.minutes} min · {block.mode === "PROTECTED" ? "Protégée" :
                        block.mode === "PREFERRED" ? "Préférentielle" : "Générale"}</small>
                      <small>Origine : {block.sources.join(", ")}</small>
                    </div>)}
                  {occurrences.filter((item) => item.original_local_date === date).map((occurrence) =>
                    <div className="availabilityOccurrence" key={occurrence.rule_id + date}>
                      <span>{timeInZone(occurrence.starts_at, zone)} · {label(occurrence.work_type_id)}</span>
                      <div className="availabilityActions">
                        <button type="button" disabled={busy} onClick={() => chooseOccurrence(occurrence, "CANCEL")}>Annuler</button>
                        <button type="button" disabled={busy} onClick={() => chooseOccurrence(occurrence, "REPLACE")}>Modifier</button>
                      </div>
                    </div>)}
                </div>;
              })}
            </div>
            <p className="muted">La grille montre la capacité effective déclarée, y compris les blocs manuels historiques. Les événements Google et réservations réduisent séparément le temps libre vérifié. Une plage qui traverse minuit est listée à son jour de départ.</p>
          </section>
          <section className="availabilityCard">
            <h3>Dérogations et exceptions</h3>
            {exceptions.length === 0 ? <p className="empty">Aucune dérogation enregistrée.</p> : (
              <ul className="availabilityRows">{exceptions.map((item) => <li key={item.id}>
                <div><strong>{item.action} · {item.enabled ? "Active" : "Désactivée"}</strong>
                  <p>{item.original_local_date || (item.starts_at && item.ends_at ?
                    describe(item.starts_at, item.ends_at) : "—")} · {item.reason || "Sans motif"}</p>
                  <small>Version {item.version}</small></div>
                <button type="button" disabled={busy} onClick={() => editException(item)}>Modifier</button>
              </li>)}</ul>
            )}
            <form onSubmit={(event) => void previewException(event)} className="availabilityForm">
              <h4>{editingException ? "Modifier la dérogation (version " + editingException.version + ")" : "Nouvelle dérogation"}</h4>
              <div className="availabilityFields">
                <label>Action<select value={exceptionDraft.action} onChange={(event) =>
                  updateException({ action: event.target.value as Action })}>
                  <option value="UNAVAILABLE">Indisponibilité réelle</option><option value="ADD">Ajouter une plage</option>
                  <option value="CANCEL">Annuler une occurrence</option><option value="REPLACE">Remplacer une occurrence</option>
                </select></label>
                {(exceptionDraft.action === "CANCEL" || exceptionDraft.action === "REPLACE") && <>
                  <label>Règle<select required value={exceptionDraft.rule_id} onChange={(event) =>
                    updateException({ rule_id: event.target.value })}>
                    <option value="">Choisir…</option>
                    {rules.map((rule) => <option key={rule.id} value={rule.id}>{shortId(rule.id)}</option>)}
                  </select></label>
                  <label>Date d'occurrence d'origine<input type="date" required value={exceptionDraft.original_local_date}
                    onChange={(event) => updateException({ original_local_date: event.target.value })} /></label>
                </>}
                {exceptionDraft.action !== "CANCEL" && <>
                  <label>Début<input type="datetime-local" required value={exceptionDraft.starts_at}
                    onChange={(event) => updateException({ starts_at: event.target.value })} /></label>
                  <label>Fin<input type="datetime-local" required value={exceptionDraft.ends_at}
                    onChange={(event) => updateException({ ends_at: event.target.value })} /></label>
                </>}
                {exceptionDraft.action !== "CANCEL" && exceptionDraft.action !== "UNAVAILABLE" && <>
                  <label>Nature<select value={exceptionDraft.kind} onChange={(event) =>
                    updateException({ kind: event.target.value as Kind })}>
                    <option value="GENERAL">Générale</option><option value="CATEGORIZED">Par type</option>
                  </select></label>
                  {exceptionDraft.kind === "CATEGORIZED" && <>
                    <label>Type<select required value={exceptionDraft.work_type_id} onChange={(event) =>
                      updateException({ work_type_id: event.target.value })}>
                      <option value="">Choisir…</option>
                      {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
                    </select></label>
                    <label>Mode<select value={exceptionDraft.mode} onChange={(event) =>
                      updateException({ mode: event.target.value as Mode })}>
                      <option value="PREFERRED">Préférentielle</option><option value="PROTECTED">Protégée</option>
                    </select></label>
                  </>}
                </>}
                <label>Fuseau IANA<input value={exceptionDraft.timezone_name}
                  onChange={(event) => updateException({ timezone_name: event.target.value })} /></label>
                <label>Raison<textarea value={exceptionDraft.reason}
                  onChange={(event) => updateException({ reason: event.target.value })} /></label>
                {editingException && <label><input type="checkbox" checked={exceptionDraft.enabled}
                  onChange={(event) => updateException({ enabled: event.target.checked })} />Dérogation active</label>}
              </div>
              <p className="muted">Les dates avec heures utilisent le fuseau du navigateur ({browserZone}); le serveur vérifie le fuseau IANA et les transitions DST. Annuler une occurrence ne rend pas sa capacité générale.</p>
              <div className="availabilityActions"><button disabled={busy}>Prévisualiser les conséquences</button>
                {editingException && <button type="button" onClick={() => { setEditingException(null);
                  setExceptionDraft(initialException); setExceptionPreview(null); }}>Nouvelle exception</button>}</div>
            </form>
            {exceptionPreview && <div className="availabilityPreview" aria-live="polite">
              <h4>Aperçu non engageant</h4>
              <p>Nouvelle capacité déclarée : {exceptionPreview.snapshot.declared_minutes} min sur la période du {exceptionPreview.snapshot.from} au {exceptionPreview.snapshot.to} (fin exclusive).</p>
              {exceptionPreview.snapshot.issues.length === 0 ? <p>Aucun conflit détecté dans cette projection.</p> : (
                <ul>{exceptionPreview.snapshot.issues.map((issue, index) => <li key={index}>
                  <strong>{issue.code}</strong> · {describe(issue.starts_at, issue.ends_at)}
                  {issue.booking_id && <p>Réservation {shortId(issue.booking_id)} conservée; une décision séparée sera nécessaire.</p>}
                </li>)}</ul>
              )}
              {exceptionPreview.snapshot.expansion_issues.map((issue, index) => <p className="error" key={index}>
                Date {issue.original_local_date} : {issue.reason}</p>)}
              <button type="button" disabled={busy} onClick={() => void applyException()}>
                Confirmer la dérogation{exceptionPreview.snapshot.issues.some((issue) => issue.booking_id) ?
                  " et reconnaître les conflits" : ""}</button>
            </div>}
          </section>
          <section className="availabilityCard">
            <h3>Conflits et réservations</h3>
            {projection?.issues.filter((issue) => !issue.booking_id).map((issue, index) =>
              <p key={index} className="availabilityDiagnostic">{issue.code} · {describe(issue.starts_at, issue.ends_at)} · {issue.sources.join(", ")}</p>)}
            {projection?.expansion_issues.map((issue, index) =>
              <p key={index} role="status" className="availabilityDiagnostic">Règle {shortId(issue.rule_id)} le {issue.original_local_date} : {issue.reason}</p>)}
            {activeIssues.length === 0 ? <p className="empty">Aucun conflit ouvert de réservation dans cette semaine.</p> : (
              <ul className="availabilityRows">{activeIssues.map((issue, index) =>
                <li key={index}><div><strong>{issue.code} · OPEN</strong>
                  <p>{describe(issue.starts_at, issue.ends_at)} · réservation {shortId(issue.booking_id || "")}</p>
                  <small>Origine : {issue.sources.join(", ")}</small></div>
                  {conflictBookings.some((booking) => booking.id === issue.booking_id) &&
                    <button type="button" onClick={() => { setResolutionId(issue.booking_id || "");
                      setResolutionPreview(null); setHistory([]); }}>Résoudre</button>}
                </li>)}</ul>
            )}
            {conflictBookings.length > 0 && <form onSubmit={(event) => void previewResolution(event)}
              className="availabilityForm">
              <h4>Décision explicite de réservation</h4>
              <label>Réservation en conflit<select required value={resolutionId} onChange={(event) => {
                setResolutionId(event.target.value); setResolutionPreview(null); setHistory([]);
              }}>
                <option value="">Choisir une réservation…</option>
                {conflictBookings.map((booking) => <option key={booking.id} value={booking.id}>
                  {shortId(booking.id)} · {describe(booking.starts_at, booking.ends_at)}
                </option>)}
              </select></label>
              <div className="availabilityFields">
                <label>Décision<select value={resolutionDecision} onChange={(event) => {
                  setResolutionDecision(event.target.value as ResolutionDecision); setResolutionPreview(null);
                }}>
                  <option value="KEEP">Conserver temporairement le conflit</option>
                  <option value="CANCEL">Annuler la réservation locale</option>
                  <option value="MOVE">Déplacer la réservation locale</option>
                </select></label>
                {resolutionDecision === "MOVE" && <>
                  <label>Nouveau début<input required type="datetime-local" value={moveStart}
                    onChange={(event) => { setMoveStart(event.target.value); setResolutionPreview(null); }} /></label>
                  <label>Nouvelle fin<input required type="datetime-local" value={moveEnd}
                    onChange={(event) => { setMoveEnd(event.target.value); setResolutionPreview(null); }} /></label>
                </>}
                <label>Raison de la décision<input required maxLength={500} value={resolutionReason}
                  onChange={(event) => { setResolutionReason(event.target.value); setResolutionPreview(null); }} /></label>
              </div>
              <div className="availabilityActions">
                <button type="submit" disabled={busy || !selectedBooking}>Prévisualiser la résolution</button>
                {selectedBooking && <button type="button" onClick={() => void showHistory(selectedBooking.id)}>
                  Voir l'historique</button>}
              </div>
              {history.length > 0 && <ul>{history.map((item, index) =>
                <li key={index}>{item.event_type} · {new Date(item.occurred_at).toLocaleString()}</li>)}</ul>}
            </form>}
            {resolutionPreview && <div className="availabilityPreview" aria-live="polite">
              <h4>Conséquences proposées — {resolutionPreview.snapshot.decision}</h4>
              <ul>{resolutionPreview.snapshot.consequences.map((item, index) => <li key={index}>{item}</li>)}</ul>
              <p>Conflits : {resolutionPreview.snapshot.conflict_codes.join(", ") || "aucun"}.
                Vérification externe : {resolutionPreview.snapshot.calendar_checked ? "effectuée" : "non requise"}.
                Aucune écriture Google Calendar.</p>
              {resolutionPreview.snapshot.replacement && <p>Nouvelle plage : {describe(
                resolutionPreview.snapshot.replacement.starts_at, resolutionPreview.snapshot.replacement.ends_at)}</p>}
              <button type="button" disabled={busy} onClick={() => void confirmResolution()}>Confirmer cette décision</button>
            </div>}
            <p className="muted">KEEP préserve le conflit OPEN. CANCEL ou MOVE s'applique uniquement à une réservation TaskPlanner après revalidation et consentement explicite. En cas de 409, l'aperçu doit être refait.</p>
          </section>
        </div>
      )}
    </section>
  );
}
