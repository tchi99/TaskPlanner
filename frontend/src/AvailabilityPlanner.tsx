import { FormEvent, useCallback, useEffect, useState } from "react";
import { apiFetch } from "./auth";
import "./availability.css";
import { WeeklyScheduleEditor } from "./WeeklyScheduleEditor";
import { WeeklyEligibilityChart } from "./WeeklyEligibilityChart";
import { ScheduleCategories, type ScopeCatalog } from "./ScheduleCategories";
import { AvailabilitySetupGuide, AvailabilityEmptyState, NewAvailabilityWindowForm } from "./availability-setup/FirstAvailabilitySetup";
import type { WindowPreviewRequest } from "./availability-setup/model";

type WorkType = { id: string; name: string; scope_id: string };
type TaskChoice = { id: string; title: string; status: string; work_type_id: string | null };
type Mode = "PROTECTED" | "PREFERRED";
type Kind = "GENERAL" | "CATEGORIZED";
type Action = "CANCEL" | "REPLACE" | "ADD" | "UNAVAILABLE";
type Revision = {
  number: number; effective_from: string; valid_until: string | null;
  timezone_name: string; days_of_week: number[]; starts_at_local: string;
  ends_at_local: string; kind: Kind; work_type_id: string | null; scope_id?: string | null;
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
    mode: Mode | null; scope_id?: string | null; sources: string[]; minutes: number }[];
  issues: ProjectionIssue[];
  expansion_issues: { rule_id: string; revision: number; original_local_date: string; reason: string }[];
};
type Exception = {
  id: string; version: number; action: Action; rule_id: string | null;
  original_local_date: string | null; starts_at: string | null; ends_at: string | null;
  timezone_name: string; kind: Kind | null; work_type_id: string | null;
  mode: Mode | null; scope_id?: string | null; enabled: boolean; reason: string | null;
};
type Booking = {
  id: string; task_id: string; segment_id?: string | null; work_type_id: string | null; starts_at: string;
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
const initialException = {
  action: "UNAVAILABLE" as Action, rule_id: "", original_local_date: "",
  starts_at: "", ends_at: "", timezone_name: browserZone,
  kind: "GENERAL" as Kind, work_type_id: "", mode: "PREFERRED" as Mode,
  enabled: true, reason: "", scope_id: "",
};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = response.status === 409 ? "Réservation ou aperçu périmé (409). Actualise et recommence l’aperçu." :
      typeof data?.detail === "string" ? data.detail :
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

export function AvailabilityPlanner({ workTypes, tasks, onWorkTypesChanged }: {
  workTypes: WorkType[]; tasks: TaskChoice[]; onWorkTypesChanged: () => Promise<void>;
}) {
  const [tab, setTab] = useState<"rules" | "real">("rules");
  const [weeklyGridDirty, setWeeklyGridDirty] = useState(false);
  const [catalog, setCatalog] = useState<ScopeCatalog | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [selectedScopeId, setSelectedScopeId] = useState("");
  const [week, setWeek] = useState(() => weekOf(dateISO(new Date())));
  const [zone, setZone] = useState(browserZone);
  const [zoneInput, setZoneInput] = useState(browserZone);
  const [rules, setRules] = useState<Rule[]>([]);
  const [occurrences, setOccurrences] = useState<Occurrence[]>([]);
  const [exceptions, setExceptions] = useState<Exception[]>([]);
  const [projection, setProjection] = useState<Projection | null>(null);
  const [verified, setVerified] = useState<Verified | null>(null);
  const [verifiedError, setVerifiedError] = useState("");
  const [commitments, setCommitments] = useState<{ calendar_id: string; event_id: string; title: string; starts_at: string; ends_at: string }[]>([]);
  const [commitmentsError, setCommitmentsError] = useState("");
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [exceptionDraft, setExceptionDraft] = useState(initialException);
  const [editingException, setEditingException] = useState<Exception | null>(null);
  const [exceptionPreview, setExceptionPreview] = useState<{
    snapshot: ExceptionPreview; payload: object; version: number | null; id: string | null;
  } | null>(null);
  const [resolutionId, setResolutionId] = useState("");
  const [resolutionDecision, setResolutionDecision] = useState<ResolutionDecision>("CANCEL");
  const [resolutionReason, setResolutionReason] = useState("");
  const [moveStart, setMoveStart] = useState("");
  const [moveEnd, setMoveEnd] = useState("");
  const [resolutionPreview, setResolutionPreview] = useState<{
    bookingId: string; weekStart: string; booking: Booking; payload: object; snapshot: ResolutionPreview;
  } | null>(null);
  const [history, setHistory] = useState<{ event_type: string; occurred_at: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [newWindowOpen, setNewWindowOpen] = useState(false);
  const [newWindowBusy, setNewWindowBusy] = useState(false);
  const [newWindowError, setNewWindowError] = useState("");
  const [windowAcknowledged, setWindowAcknowledged] = useState(false);
  const [windowPreview, setWindowPreview] = useState<{
    draft: Record<string, unknown> & { draft_id: string };
    snapshot: {
      fingerprint: string; blocking_issues: string[]; consequences: string[];
      before_physical_minutes: number; after_physical_minutes: number;
      booking_inventory: { id: string }[]; calendar_checked: boolean;
    };
  } | null>(null);
  const [hasPermission, setHasPermission] = useState(false);
  const [chartRevision, setChartRevision] = useState(0);
  const envelopeParentIds = Array.from(new Set(rules.flatMap((rule) =>
    rule.revisions.filter((revision) => revision.kind === "GENERAL" &&
      revision.enabled && revision.scope_id).map((revision) => revision.scope_id!))));
  const eligibleParents = catalog?.scopes.filter((scope) => scope.state === "ACTIVE") || [];
  const minimumEffectiveDate = shiftDay(dayInZone(new Date().toISOString(), zone), 1);
  const progress = {
    hasParent: eligibleParents.length > 0,
    hasWorkType: workTypes.some((type) => eligibleParents.some((scope) => scope.id === type.scope_id)),
    hasEnvelope: envelopeParentIds.length > 0,
    hasPermission,
  };
  function focusSetup(id: string) {
    document.getElementById(id)?.focus();
  }
  async function previewNewWindow(request: WindowPreviewRequest) {
    setNewWindowError(""); setWindowPreview(null); setWindowAcknowledged(false);
    const draft = {
      draft_id: crypto.randomUUID(), series_id: null, scope_id: request.parentId,
      work_type_id: request.workTypeId, expected_version: 0,
      effective_from: request.effectiveDate, timezone_name: request.timezone,
      days_of_week: request.daysOfWeek, starts_at_local: request.startTime,
      ends_at_local: request.endTime, priority_rank: request.priority,
      enabled: true, start_fold: null, end_fold: null,
    };
    try {
      const snapshot = await api<{
        fingerprint: string; blocking_issues: string[]; consequences: string[];
        before_physical_minutes: number; after_physical_minutes: number;
        booking_inventory: { id: string }[]; calendar_checked: boolean;
      }>("/api/availability/eligibility-edits/preview", {
        method: "POST", headers, body: JSON.stringify(draft),
      });
      setWindowPreview({ draft, snapshot });
    } catch (reason: unknown) {
      setNewWindowError(reason instanceof Error ? reason.message : "Aperçu impossible.");
      throw reason;
    }
  }
  async function confirmNewWindow() {
    if (!windowPreview || windowPreview.snapshot.blocking_issues.length ||
      (windowPreview.snapshot.booking_inventory.length && !windowAcknowledged)) return;
    if (!window.confirm("Confirmer cette permission future ? Les réservations restent inchangées.")) return;
    setNewWindowBusy(true); setNewWindowError("");
    try {
      await api("/api/availability/eligibility-edits/confirm", {
        method: "POST", headers, body: JSON.stringify({
          ...windowPreview.draft, command_id: windowPreview.draft.draft_id,
          fingerprint: windowPreview.snapshot.fingerprint,
          confirmed: true, acknowledge_bookings: windowAcknowledged,
        }),
      });
      setNewWindowOpen(false); setWindowPreview(null); setHasPermission(true);
      setChartRevision((value) => value + 1);
      await reload();
      setNotice("Permission enregistrée. Aucune réservation ni événement Google déplacé.");
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Confirmation impossible.";
      setNewWindowError(message + " Le brouillon est conservé.");
      if (message.includes("(409)")) setWindowPreview(null);
    } finally { setNewWindowBusy(false); }
  }

  const label = (id: string | null) =>
    id ? workTypes.find((type) => type.id === id)?.name || "Type " + shortId(id) : "Non classé (NULL)";
  const scopeLabel = (id: string | null | undefined) =>
    !id ? "Global" :
      catalog?.scopes.find((scope) => scope.id === id)?.name || "Parent " + shortId(id);
  const sectionLabel = (typeId: string | null, scopeId: string | null | undefined) =>
    typeId ? label(typeId) + " · " + scopeLabel(scopeId) :
      "Général (NULL) · " + scopeLabel(scopeId);
  const refreshCatalog = useCallback(async () => {
    const result = await api<ScopeCatalog>("/api/schedule-scopes");
    setCatalog(result); setCatalogError("");
    setSelectedScopeId((old) => result.scopes.some((scope) =>
      scope.id === old && scope.state === "ACTIVE") ? old :
      result.scopes.find((scope) => scope.state === "ACTIVE")?.id || "");
  }, []);
  useEffect(() => {
    void refreshCatalog().catch((reason: unknown) => setCatalogError(
      reason instanceof Error ? reason.message : "Impossible de lire les catégories parentes."));
  }, [refreshCatalog]);
  function selectScope(id: string) {
    if (id === selectedScopeId) return;
    if (weeklyGridDirty && !window.confirm(
      "Changer de parent abandonnera le brouillon hebdomadaire non enregistré. Continuer ?")) return;
    setSelectedScopeId(id); setWeeklyGridDirty(false);
    setWindowPreview(null); setHasPermission(false);
  }
  useEffect(() => {
    if (!selectedScopeId) { setHasPermission(false); return; }
    let active = true;
    const query = new URLSearchParams({
      week_start: week, timezone_name: zone, scope_id: selectedScopeId,
    });
    void api<{ potential_minutes: { work_type_id: string; minutes: number }[] }>(
      "/api/availability/eligibility-week?" + query,
    ).then((result) => {
      if (active) setHasPermission(result.potential_minutes.some((item) => item.minutes > 0));
    }).catch(() => { if (active) setHasPermission(false); });
    return () => { active = false; };
  }, [selectedScopeId, week, zone, chartRevision]);
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
    setCommitments([]); setCommitmentsError("");
    setExceptionPreview(null); setResolutionPreview(null); setResolutionId(""); setHistory([]);
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
      setVerified(null); setCommitments([]);
      setNotice(success);
    } catch (err: unknown) {
      setExceptionPreview(null); setResolutionPreview(null);
      setError(err instanceof Error ? err.message : "Opération impossible.");
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
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
      enabled: value.enabled, reason: value.reason || "", scope_id: value.scope_id || "",
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
      kind: action === "UNAVAILABLE" || action === "CANCEL" ? null : "GENERAL",
      work_type_id: null,
      mode: null,
      enabled: exceptionDraft.enabled, reason: exceptionDraft.reason.trim() || null,
      scope_id: action === "CANCEL" || action === "REPLACE" ? null : exceptionDraft.scope_id || null,
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
    setVerified(null); setVerifiedError(""); setCommitments([]); setCommitmentsError("");
    try {
      const verifiedResult = await api<Verified>("/api/availability/verified?week_start=" +
        week + "&timezone_name=" + encodeURIComponent(zone));
      setVerified(verifiedResult);
      try {
        const result = await api<{ commitments: typeof commitments }>(
          "/api/capacity/weeks/" + week + "/calendar?timezone_name=" + encodeURIComponent(zone));
        setCommitments(result.commitments);
      } catch {
        setCommitmentsError("Liste des événements Google indisponible; le contrôle de capacité reste distinct.");
      }
    } catch (err: unknown) {
      setVerifiedError((err instanceof Error ? err.message : "Vérification indisponible.") +
        " La capacité déclarée n'est pas du temps libre confirmé.");
    }
  }

  const activeIssues = [...(projection?.issues || []), ...(verified?.issues || [])]
    .filter((issue, index, source) => issue.booking_id && issue.state === "OPEN" &&
      source.findIndex((other) => other.booking_id === issue.booking_id &&
        other.code === issue.code && other.starts_at === issue.starts_at) === index);
  const activeBookings = bookings.filter((booking) => booking.status === "CONFIRMED" &&
    dayInZone(booking.starts_at, zone) >= week && dayInZone(booking.starts_at, zone) < shiftDay(week, 7));
  const conflictBookings = activeBookings.filter((booking) =>
    activeIssues.some((issue) => issue.booking_id === booking.id));
  const selectedBooking = activeBookings.find((booking) => booking.id === resolutionId);
  const selectedHasConflict = !!selectedBooking && conflictBookings.some((item) => item.id === selectedBooking.id);
  function selectBooking(bookingId: string, decision: ResolutionDecision = "CANCEL") {
    setResolutionId(bookingId); setResolutionDecision(decision);
    setResolutionReason(decision === "CANCEL" ? "Annulation manuelle" : "");
    setResolutionPreview(null); setHistory([]);
  }
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
      setResolutionPreview({ bookingId: selectedBooking.id, weekStart: week,
        booking: selectedBooking, payload, snapshot });
    } catch (err: unknown) { setError(err instanceof Error ? err.message : "Aperçu de résolution impossible."); }
    finally { setBusy(false); }
  }
  async function confirmResolution() {
    if (!resolutionPreview || busy || !window.confirm(resolutionPreview.snapshot.decision === "CANCEL" ?
      "Annuler uniquement la réservation sélectionnée ? La tâche et les règles habituelles restent inchangées; aucun événement Google modifié." :
      "Confirmer cette décision locale et son audit ?")) return;
    const draft = resolutionPreview;
    await operate(async () => {
      await api("/api/capacity/weeks/" + draft.weekStart + "/time-blocks/" +
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
        <div><h2>Disponibilités</h2><p>Configure les parents, les enveloppes et les permissions depuis un seul espace.</p></div>
        <div className="availabilitySwitch" role="group" aria-label="Configuration et exceptions">
          <button type="button" aria-pressed={tab === "rules"} className={tab === "rules" ? "selected" : ""}
            onClick={() => setTab("rules")}>Configuration</button>
          <button type="button" aria-pressed={tab === "real"} className={tab === "real" ? "selected" : ""}
            onClick={() => {
              if (weeklyGridDirty && !window.confirm("Abandonner les changements non enregistrés de l'enveloppe ?")) return;
              setTab("real");
            }}>Exceptions physiques et réservations</button>
        </div>
      </div>
      <div className="availabilityToolbar">
        <label>Semaine du lundi
          <input type="date" value={week} onChange={(event) => setWeek(weekOf(event.target.value || week))} />
        </label>
        <button type="button" onClick={() => setWeek(shiftDay(week, -7))} aria-label="Semaine précédente">←</button>
        <button type="button" onClick={() => setWeek(shiftDay(week, 7))} aria-label="Semaine suivante">→</button>
        <label>Fuseau de lecture
          <input value={zoneInput} onChange={(event) => setZoneInput(event.target.value)} aria-label="Fuseau horaire IANA" />
        </label>
        <button type="button" onClick={() => {
          try {
            new Intl.DateTimeFormat("fr-CA", { timeZone: zoneInput });
            if (zoneInput !== zone && weeklyGridDirty &&
                !window.confirm("Changer de fuseau abandonnera le brouillon de grille non enregistré. Continuer ?")) return;
            setZone(zoneInput); setError("");
          }
          catch { setError("Fuseau IANA invalide."); }
        }}>Appliquer le fuseau</button>
        <button type="button" onClick={() => void reload().catch((err: unknown) =>
          setError(err instanceof Error ? err.message : "Actualisation impossible."))}>Actualiser</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="availabilityNotice">{notice}</p>}
      {loading ? <p role="status">Chargement des disponibilités…</p> : tab === "rules" ? (
        <div className="availabilityStack">
          {catalogError && <p role="alert" className="error">{catalogError}</p>}
          {(!progress.hasParent || !progress.hasWorkType || !progress.hasEnvelope || !progress.hasPermission) &&
            <AvailabilitySetupGuide progress={progress}
              onCreateParent={() => focusSetup("tp26-new-parent")}
              onAddWorkType={() => focusSetup("tp26-new-work-type")}
              onDefineEnvelope={() => focusSetup("tp26-envelope-date")}
              onNewWindow={() => { setNewWindowOpen(true); setWindowPreview(null); }} />}
          {catalog && <ScheduleCategories catalog={catalog} workTypes={workTypes}
            onWorkTypesChanged={onWorkTypesChanged}
            onChanged={async () => { await refreshCatalog(); await reload(); }}
            onSelectScope={selectScope} />}
          <section className="availabilityCard scopeChooser">
            <label>Catégorie parente à configurer
              <select aria-label="Catégorie parente de l'horaire" value={selectedScopeId}
                onChange={(event) => selectScope(event.target.value)}>
                <option value="">Choisir un parent</option>
                {eligibleParents.map((scope) =>
                  <option key={scope.id} value={scope.id}>{scope.name}</option>)}
              </select>
            </label>
            <p className="muted">Une enveloppe physique par parent, sans double comptage.
              Les sous-catégories partagent ses minutes admissibles.</p>
          </section>
          {selectedScopeId && <details open={!envelopeParentIds.includes(selectedScopeId)}>
            <summary>Définir ou modifier l'enveloppe physique hebdomadaire</summary>
            <WeeklyScheduleEditor key={selectedScopeId} workTypes={workTypes}
              catalog={catalog} scopeId={selectedScopeId} zone={zone}
              onSaved={async () => { await reload(); setChartRevision((value) => value + 1); }}
              onDirtyChange={setWeeklyGridDirty} />
          </details>}
          <section className="availabilityCard" aria-label="Créer une permission">
            <div className="availabilityCardHeading">
              <div><h3>Permissions récurrentes</h3>
                <p className="muted">Plusieurs activités du même parent peuvent se superposer.
                  L'aperçu serveur valide les contraintes avant l'enregistrement.</p></div>
              <button type="button" onClick={() => { setNewWindowOpen(true); setWindowPreview(null); }}>
                + Nouvelle plage
              </button>
            </div>
            {!hasPermission && <AvailabilityEmptyState />}
            {newWindowOpen && <NewAvailabilityWindowForm parents={eligibleParents.map((scope) =>
              ({ id: scope.id, label: scope.name }))}
              workTypes={workTypes.map((type) => ({
                id: type.id, parentId: type.scope_id, label: type.name,
              }))}
              envelopeParentIds={envelopeParentIds} initialTimezone={zone}
              minimumEffectiveDate={minimumEffectiveDate}
              onPreview={previewNewWindow} onDraftChanged={() => setWindowPreview(null)}
              onCancel={() => { setNewWindowOpen(false); setWindowPreview(null); }} />}
            {newWindowError && <p role="alert" className="error">{newWindowError}</p>}
            {windowPreview && <div className="availabilityPreview" aria-live="polite">
              <h4>Aperçu serveur de la nouvelle permission</h4>
              <p>Capacité physique avant : {windowPreview.snapshot.before_physical_minutes} min ;
                après : {windowPreview.snapshot.after_physical_minutes} min. Les permissions
                simultanées ne s'additionnent pas.</p>
              <ul>{windowPreview.snapshot.consequences.map((value, index) =>
                <li key={index}>{value}</li>)}</ul>
              {!windowPreview.snapshot.calendar_checked &&
                <p>Google non vérifié : aucun temps libre n'est présumé.</p>}
              {windowPreview.snapshot.blocking_issues.length > 0 &&
                <p role="alert" className="error">Blocages :
                  {windowPreview.snapshot.blocking_issues.join(", ")}</p>}
              {windowPreview.snapshot.booking_inventory.length > 0 &&
                <label><input type="checkbox" checked={windowAcknowledged}
                  onChange={(event) => setWindowAcknowledged(event.target.checked)} />
                  Je reconnais que {windowPreview.snapshot.booking_inventory.length} réservation(s)
                  confirmée(s) restent inchangées.</label>}
              <button type="button" disabled={newWindowBusy ||
                windowPreview.snapshot.blocking_issues.length > 0 ||
                (windowPreview.snapshot.booking_inventory.length > 0 && !windowAcknowledged)}
                onClick={() => void confirmNewWindow()}>
                {newWindowBusy ? "Enregistrement…" : "Confirmer la nouvelle plage"}</button>
            </div>}
          </section>
          {selectedScopeId && <WeeklyEligibilityChart key={selectedScopeId + ":" + chartRevision}
            week={week} zone={zone} scopeId={selectedScopeId}
            catalog={catalog} workTypes={workTypes} tasks={tasks}
            onSelectScope={selectScope} />}
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
            {verified && <div className="availabilityExternal"><h4>Engagements Google occupés (lecture seule)</h4>
              {commitmentsError && <p role="status">{commitmentsError}</p>}
              {!commitmentsError && commitments.length === 0 && <p className="empty">Aucun engagement occupé trouvé.</p>}
              <ul>{commitments.map((item) => <li key={item.calendar_id + ":" + item.event_id}>
                {item.title} · {describe(item.starts_at, item.ends_at)}</li>)}</ul>
            </div>}
            <div className="availabilityWeekGrid" aria-label="Grille hebdomadaire réelle">
              {weekdays.map((day, index) => {
                const date = shiftDay(week, index);
                const blocks = projection?.blocks.filter((block) => dayInZone(block.starts_at, zone) === date) || [];
                return <div className="availabilityDay" key={date}>
                  <h4>{day} <small>{date.slice(5)}</small></h4>
                  {blocks.length === 0 ? <p className="empty">Aucune plage</p> :
                    blocks.map((block) => <div className="availabilitySlot GENERAL" key={block.id}>
                      <strong>{timeInZone(block.starts_at, zone)}–{timeInZone(block.ends_at, zone)}</strong>
                      <span>{sectionLabel(block.work_type_id, block.scope_id)}</span>
                      <small>{block.minutes} min · capacité physique déclarée</small>
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
            <p className="muted">La grille décrit la capacité physique déclarée et ses exceptions datées. Les événements Google et réservations réduisent séparément le temps libre vérifié. Une plage qui traverse minuit est listée à son jour de départ.</p>
          </section>
          <section className="availabilityCard">
            <h3>Dérogations et exceptions</h3>
            {exceptions.length === 0 ? <p className="empty">Aucune dérogation enregistrée.</p> : (
              <ul className="availabilityRows">{exceptions.map((item) => <li key={item.id}>
                <div><strong>{item.action} · {item.enabled ? "Active" : "Désactivée"}</strong>
                  <p>{item.original_local_date || (item.starts_at && item.ends_at ?
                    describe(item.starts_at, item.ends_at) : "—")} · {item.reason || "Sans motif"}</p>
                  <small>Version {item.version} · {scopeLabel(item.scope_id)}</small></div>
                <button type="button" disabled={busy} onClick={() => editException(item)}>Modifier</button>
              </li>)}</ul>
            )}
            <form onSubmit={(event) => void previewException(event)} className="availabilityForm">
              <h4>{editingException ? "Modifier la dérogation (version " + editingException.version + ")" : "Nouvelle dérogation"}</h4>
              <div className="availabilityFields">
                <label>Action<select value={exceptionDraft.action} onChange={(event) =>
                  updateException({ action: event.target.value as Action })}>
                  <option value="UNAVAILABLE">Indisponibilité physique</option><option value="ADD">Disponibilité physique datée</option>
                  <option value="CANCEL">Annuler une occurrence</option><option value="REPLACE">Remplacer une occurrence</option>
                </select></label>
                {(exceptionDraft.action === "UNAVAILABLE" || exceptionDraft.action === "ADD") && <label>
                   Portée de la dérogation<select value={exceptionDraft.scope_id} onChange={(event) =>
                     updateException({ scope_id: event.target.value })}>
                     <option value="">{exceptionDraft.action === "UNAVAILABLE" ?
                       "Globale — tous les parents" : "Aucun parent"}</option>
                     {catalog?.scopes.filter((scope) => scope.state === "ACTIVE")
                       .map((scope) => <option key={scope.id} value={scope.id}>{scope.name}</option>)}
                   </select></label>}
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

        </div>
      )}

      {!loading && <section className="availabilityCard" aria-label="Réservations de la semaine">
        <h3>{tab === "rules" ? "Réservations de la semaine" : "Conflits et réservations"}</h3>
        <p className="muted">Réservations locales datées de la semaine du {week}. Annuler une réservation
          ne désactive ni ne révise les règles de l’horaire habituel et ne touche pas aux autres semaines.</p>
        <h4>Réservations locales confirmées</h4>
        {activeBookings.length === 0 ? <p className="empty">Aucune réservation locale active sur la semaine.</p> :
          <ul className="availabilityRows">{activeBookings.map((booking) => <li key={booking.id}>
            <div><strong>Tâche {shortId(booking.task_id)}{booking.segment_id ?
              " · segment " + shortId(booking.segment_id) : ""}</strong>
              <p>{shortId(booking.id)} · {describe(booking.starts_at, booking.ends_at)} · {label(booking.work_type_id)} · {booking.status}</p>
            </div>
            <button type="button" disabled={busy}
              aria-label={`Annuler la réservation ${shortId(booking.id)}`}
              onClick={() => selectBooking(booking.id)}>Annuler la réservation</button>
          </li>)}</ul>}
        {tab === "real" && <>
          {projection?.issues.filter((issue) => !issue.booking_id).map((issue, index) =>
            <p key={index} className="availabilityDiagnostic">{issue.code} · {describe(issue.starts_at, issue.ends_at)} · {issue.sources.join(", ")}</p>)}
          {projection?.expansion_issues.map((issue, index) =>
            <p key={index} role="status" className="availabilityDiagnostic">Règle {shortId(issue.rule_id)} le {issue.original_local_date} : {issue.reason}</p>)}
        </>}
        {activeIssues.length === 0 ? <p className="empty">Aucun conflit ouvert de réservation dans cette semaine.</p> : (
          <ul className="availabilityRows">{activeIssues.map((issue, index) =>
            <li key={index}><div><strong>{issue.code} · OPEN</strong>
              <p>{describe(issue.starts_at, issue.ends_at)} · réservation {shortId(issue.booking_id || "")}</p>
              <small>Origine : {issue.sources.join(", ")}</small></div>
              {conflictBookings.some((booking) => booking.id === issue.booking_id) &&
                <button type="button" disabled={busy} onClick={() => selectBooking(issue.booking_id || "", "KEEP")}>
                  Résoudre</button>}
            </li>)}</ul>
        )}
        {activeBookings.length > 0 && <form onSubmit={(event) => void previewResolution(event)}
          className="availabilityForm">
          <h4>Décision explicite de réservation</h4>
          <label>{selectedHasConflict ? "Réservation en conflit" : "Réservation locale"}
            <select required value={resolutionId} onChange={(event) => {
              const id = event.target.value;
              selectBooking(id, conflictBookings.some((item) => item.id === id) ? "KEEP" : "CANCEL");
            }}>
              <option value="">Choisir une réservation…</option>
              {activeBookings.map((booking) => <option key={booking.id} value={booking.id}>
                {shortId(booking.id)} · {describe(booking.starts_at, booking.ends_at)}
              </option>)}
            </select></label>
          <div className="availabilityFields">
            <label>Décision<select value={resolutionDecision} onChange={(event) => {
              const next = event.target.value as ResolutionDecision;
              setResolutionDecision(next); setResolutionPreview(null);
              if (next === "CANCEL" && !resolutionReason.trim()) setResolutionReason("Annulation manuelle");
            }}>
              {selectedHasConflict && <option value="KEEP">Conserver temporairement le conflit</option>}
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
            {selectedBooking && <button type="button" disabled={busy} onClick={() => void showHistory(selectedBooking.id)}>
              Voir l'historique</button>}
          </div>
          {history.length > 0 && <ul>{history.map((item, index) =>
            <li key={index}>{item.event_type} · {new Date(item.occurred_at).toLocaleString()}</li>)}</ul>}
        </form>}
        {resolutionPreview && <div className="availabilityPreview" aria-live="polite">
          <h4>Conséquences proposées — {resolutionPreview.snapshot.decision}</h4>
          <p>Réservation {shortId(resolutionPreview.bookingId)} · tâche {shortId(resolutionPreview.booking.task_id)}
            {resolutionPreview.booking.segment_id ? " · segment " + shortId(resolutionPreview.booking.segment_id) : ""}
            {" · "}{describe(resolutionPreview.booking.starts_at, resolutionPreview.booking.ends_at)}
            {" · "}{label(resolutionPreview.booking.work_type_id)}.</p>
          <ul>{resolutionPreview.snapshot.consequences.map((item, index) => <li key={index}>{item}</li>)}</ul>
          {resolutionPreview.snapshot.decision === "CANCEL" && <p>Seule cette réservation locale sera annulée.
            La tâche et son avancement restent inchangés. Les minutes pourront redevenir planifiables uniquement
            selon les autres disponibilités et contraintes; les règles récurrentes restent intactes.</p>}
          <p>Conflits : {resolutionPreview.snapshot.conflict_codes.join(", ") || "aucun"}.
            Vérification externe : {resolutionPreview.snapshot.calendar_checked ? "effectuée" : "non requise"}.
            Aucun événement Google Calendar modifié.</p>
          {resolutionPreview.snapshot.replacement && <p>Nouvelle plage : {describe(
            resolutionPreview.snapshot.replacement.starts_at, resolutionPreview.snapshot.replacement.ends_at)}</p>}
          <button type="button" disabled={busy} onClick={() => void confirmResolution()}>Confirmer cette décision</button>
          <button type="button" disabled={busy} onClick={() => setResolutionPreview(null)}>Garder la réservation</button>
        </div>}
        <p className="muted">KEEP est réservé aux conflits ouverts. CANCEL ou MOVE s'applique uniquement à une réservation TaskPlanner après revalidation et consentement explicite. En cas de 409, refaire l'aperçu.</p>
      </section>}
    </section>
  );
}
