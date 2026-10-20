import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiFetch } from "./auth";

export type EditablePermission = {
  series_id: string; expected_version: number; revision: number;
  scope_id: string; work_type_id: string; timezone_name: string;
  effective_from: string; days_of_week: number[];
  starts_at_local: string; ends_at_local: string; start_fold: number | null;
  end_fold: number | null; priority_rank: number | null;
  original_local_date: string; starts_at: string; ends_at: string;
  exception_id: string | null; exception_version: number | null; source: string;
};
export type GridIntent = {
  startsAtLocal: string; endsAtLocal: string; daysOfWeek: number[];
  targetDaysOfWeek?: number[]; startsAtInstant?: string; endsAtInstant?: string;
};
type Revision = {
  effective_from: string; valid_until?: string | null; timezone_name: string;
  days_of_week: number[]; starts_at_local: string; ends_at_local: string;
  priority_rank: number | null; enabled: boolean;
  start_fold: number | null; end_fold: number | null;
};
type Series = { id: string; version: number; revisions: Revision[] };
type Decision = { exception_id: string; expected_version: number; action: "KEEP" | "DISABLE" };
type Draft = {
  draft_id: string; series_id: string | null; scope_id: string; work_type_id: string;
  expected_version: number; effective_from: string; timezone_name: string;
  days_of_week: number[]; target_days_of_week: number[] | null;
  starts_at_local: string; ends_at_local: string; priority_rank: number | null;
  enabled: boolean; start_fold: number | null; end_fold: number | null;
  exception_decisions: Decision[];
};
type Preview = {
  fingerprint: string; blocking_issues: string[];
  booking_inventory: { id: string }[];
  before_physical_minutes?: number; after_physical_minutes?: number;
  calendar_checked: boolean; consequences?: string[]; projection_days?: number;
  unresolved_exceptions?: { exception_id: string; expected_version: number; choices: string[] }[];
  future_revisions_superseded?: number[];
};
const days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
const root = "/api/availability/eligibility-edits";
const headers = { "Content-Type": "application/json" };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error((typeof body?.detail === "string" ? body.detail : "Opération refusée") +
      " (" + response.status + ")");
  }
  return response.json() as Promise<T>;
}
function nextCivilDay(zone: string): string {
  const date = new Intl.DateTimeFormat("sv-SE", { timeZone: zone,
    year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const value = new Date(date + "T12:00:00Z");
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString().slice(0, 10);
}
function weekday(date: string): number {
  return (new Date(date + "T12:00:00Z").getUTCDay() + 6) % 7;
}

export function EligibilityContextEditor({ scopeId, workTypeId, zone, seriesId,
  selectedDate, source, initial, onClose, onSaved }: {
  scopeId: string; workTypeId: string; zone: string;
  seriesId: string | null; selectedDate: string;
  source?: EditablePermission | null; initial?: GridIntent | null;
  onClose: () => void; onSaved: () => void;
}) {
  // A source series keeps its IANA timezone, never the display timezone.
  const sourceZone = source?.timezone_name || zone;
  const minimum = nextCivilDay(sourceZone);
  const [draft, setDraft] = useState<Draft>(() => ({
    draft_id: crypto.randomUUID(), series_id: seriesId,
    scope_id: scopeId, work_type_id: workTypeId,
    expected_version: source?.expected_version || 0,
    effective_from: selectedDate > minimum ? selectedDate : minimum,
    timezone_name: sourceZone,
    days_of_week: initial?.daysOfWeek || [weekday(source?.original_local_date || selectedDate)],
    target_days_of_week: initial?.targetDaysOfWeek || (source ? [weekday(source.original_local_date)] : null),
    starts_at_local: initial?.startsAtLocal || source?.starts_at_local || "09:00",
    ends_at_local: initial?.endsAtLocal || source?.ends_at_local || "10:00",
    priority_rank: source?.priority_rank ?? null, enabled: true,
    start_fold: source?.start_fold ?? null, end_fold: source?.end_fold ?? null,
    exception_decisions: [],
  }));
  const [mode, setMode] = useState<"future" | "dated">("future");
  const [datedAction, setDatedAction] = useState<"MOVE" | "REMOVE">("MOVE");
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(!seriesId || !!source);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [unresolved, setUnresolved] = useState<NonNullable<Preview["unresolved_exceptions"]>>([]);
  const previewToken = useRef(0);

  useEffect(() => {
    if (!seriesId || source) return;
    let active = true;
    void request<Series>(root + "/series/" + seriesId).then((result) => {
      if (!active) return;
      const revision = [...result.revisions].reverse().find((item) =>
        item.effective_from <= selectedDate &&
        (!item.valid_until || item.valid_until > selectedDate)) || result.revisions[result.revisions.length - 1];
      setDraft((previous) => ({
        ...previous, expected_version: result.version, timezone_name: revision.timezone_name,
        days_of_week: initial?.daysOfWeek || [...revision.days_of_week],
        starts_at_local: initial?.startsAtLocal || revision.starts_at_local,
        ends_at_local: initial?.endsAtLocal || revision.ends_at_local,
        priority_rank: revision.priority_rank,
        start_fold: revision.start_fold, end_fold: revision.end_fold, enabled: revision.enabled,
      }));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Lecture impossible.");
    }).finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [seriesId, selectedDate, source, initial]);

  function change(patch: Partial<Draft>) {
    previewToken.current++;
    setDraft((value) => ({ ...value, ...patch, draft_id: crypto.randomUUID() }));
    setPreview(null); setAcknowledged(false); setError("");
  }
  function offsetInstant(iso: string) {
    // MOVE needs wall-clock + explicit offset in the series timezone. UTC ISO
    // instants (Z) are not an accepted local-wall-time representation.
    const date = new Date(iso);
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone: sourceZone,
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit",
      minute: "2-digit", second: "2-digit", hourCycle: "h23",
      timeZoneName: "longOffset",
    }).formatToParts(date);
    const part = (kind: string) => parts.find((p) => p.type === kind)?.value || "";
    const offset = part("timeZoneName").replace("GMT", "") || "+00:00";
    return part("year") + "-" + part("month") + "-" + part("day") +
      "T" + part("hour") + ":" + part("minute") + ":" + part("second") + offset;
  }
  const datePayload = () => {
    if (!source) throw new Error("Occurrence source requise.");

    return {
      draft_id: draft.draft_id, series_id: source.series_id, exception_id: source.exception_id,
      expected_version: source.exception_version ?? 0,
      original_local_date: source.original_local_date, timezone_name: source.timezone_name,
      action: datedAction,
      starts_at: datedAction === "MOVE" ? (initial?.startsAtInstant ? offsetInstant(initial.startsAtInstant) : source.starts_at) : null,
      ends_at: datedAction === "MOVE" ? (initial?.endsAtInstant ? offsetInstant(initial.endsAtInstant) : source.ends_at) : null,
      enabled: true,
    };
  };
  async function showPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setPreview(null);
    const token = ++previewToken.current;
    try {
      const endpoint = mode === "dated" ? "/exceptions/preview" : "/preview";
      const payload = mode === "dated" ? datePayload() : draft;
      const result = await request<Preview>(root + endpoint,
        { method: "POST", headers, body: JSON.stringify(payload) });
      if (token === previewToken.current) {
        setPreview(result); setUnresolved(result.unresolved_exceptions || []);
        setAcknowledged(false);
      }
    } catch (reason: unknown) {
      if (token === previewToken.current)
        setError(reason instanceof Error ? reason.message : "Aperçu impossible.");
    } finally { if (token === previewToken.current) setBusy(false); }
  }
  async function confirm() {
    if (!preview || preview.blocking_issues.length ||
      (preview.booking_inventory.length > 0 && !acknowledged)) return;
    if (!window.confirm("Confirmer après cet aperçu ? Aucune réservation et aucun événement Google ne seront déplacés.")) return;
    setBusy(true); setError("");
    try {
      const path = mode === "dated" ? "/exceptions/confirm" : "/confirm";
      const payload = mode === "dated" ? datePayload() : draft;
      await request(root + path, { method: "POST", headers,
        body: JSON.stringify({ ...payload, command_id: draft.draft_id,
          fingerprint: preview.fingerprint, confirmed: true, acknowledge_bookings: acknowledged }) });
      onSaved(); onClose();
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Confirmation impossible.";
      setError(message + " Le brouillon est conservé; demander un nouvel aperçu en cas de 409.");
      if (message.includes("(409)")) setPreview(null);
    } finally { setBusy(false); }
  }

  return <section className="eligEdit" aria-label="Panneau contextuel de la grille">
    <div className="availabilityCardHeading">
      <div><h4>{source ? "Modifier une permission" : "Nouvelle permission"}</h4>
        <p className="muted">Activité {workTypeId} · fuseau de la série {draft.timezone_name}.
          Un geste n'enregistre rien avant l'aperçu et ta confirmation.</p></div>
      <button type="button" onClick={onClose} disabled={busy}>Annuler le brouillon</button>
    </div>
    {!loaded && <p role="status">Lecture de la révision applicable…</p>}
    {loaded && <form className="eligEditForm" onSubmit={(event) => void showPreview(event)}>
      {source && <fieldset><legend>Portée de l'édition</legend>
        <label><input type="radio" name={"edit-mode-" + draft.draft_id}
          checked={mode === "future"} onChange={() => { setMode("future"); previewToken.current++; setBusy(false); setPreview(null); }} />
          Occurrences futures des jours ciblés</label>
        <label><input type="radio" name={"edit-mode-" + draft.draft_id}
          checked={mode === "dated"} onChange={() => { setMode("dated"); previewToken.current++; setBusy(false); setPreview(null); }} />
          Cette occurrence datée uniquement ({source.original_local_date})</label>
      </fieldset>}
      {mode === "future" ? <>
        <label>Date d'effet<input type="date" min={minimum} required value={draft.effective_from}
          onChange={(event) => change({ effective_from: event.target.value })} /></label>
        <label>Début local<input type="time" step={60} required value={draft.starts_at_local}
          onChange={(event) => change({ starts_at_local: event.target.value })} /></label>
        <label>Fin locale (24:00 permis)<input type="text" inputMode="numeric" required
          pattern="([01][0-9]|2[0-3]):[0-5][0-9]|24:00" value={draft.ends_at_local}
          onChange={(event) => change({ ends_at_local: event.target.value })} /></label>
        <label>Rang contextuel (vide = neutre)<input type="number" min={1}
          value={draft.priority_rank ?? ""} onChange={(event) =>
            change({ priority_rank: event.target.value ? Number(event.target.value) : null })} /></label>
        <fieldset><legend>Jours d'admissibilité après modification</legend>
          {days.map((day, index) => <label key={day}><input type="checkbox"
            checked={draft.days_of_week.includes(index)}
            onChange={(event) => change({ days_of_week: event.target.checked ?
              [...draft.days_of_week, index].sort((a,b) => a-b) :
              draft.days_of_week.filter((x) => x !== index) })} />{day}</label>)}
        </fieldset>
        {source && <fieldset><legend>Jours d'origine à réviser (autres jours préservés)</legend>
          {source.days_of_week.map((n) => <label key={n}><input type="checkbox"
            checked={draft.target_days_of_week?.includes(n) || false}
            onChange={(event) => change({ target_days_of_week: event.target.checked ?
              [...(draft.target_days_of_week || []), n].sort((a,b) => a-b) :
              (draft.target_days_of_week || []).filter((x) => x !== n) })} />{days[n]}</label>)}
        </fieldset>}
        <label><input type="checkbox" checked={draft.enabled}
          onChange={(event) => change({ enabled: event.target.checked })} />Permission activée</label>
        <label>Début ambigu DST<select value={draft.start_fold === null ? "" : draft.start_fold}
          onChange={(event) => change({ start_fold: event.target.value === "" ? null : Number(event.target.value) })}>
          <option value="">Automatique</option><option value={0}>Premier instant</option><option value={1}>Second instant</option>
        </select></label>
        <label>Fin ambiguë DST<select value={draft.end_fold === null ? "" : draft.end_fold}
          onChange={(event) => change({ end_fold: event.target.value === "" ? null : Number(event.target.value) })}>
          <option value="">Automatique</option><option value={0}>Premier instant</option><option value={1}>Second instant</option>
        </select></label>
      </> : <>
        <label>Action datée<select value={datedAction}
          onChange={(event) => { setDatedAction(event.target.value as "MOVE" | "REMOVE"); previewToken.current++; setBusy(false); setPreview(null); }}>
          <option value="MOVE">Déplacer cette occurrence</option>
          <option value="REMOVE">Retirer cette occurrence</option>
        </select></label>
        {datedAction === "MOVE" && <p className="muted">Les instants précis du geste sont utilisés pour
          l'exception datée. Pour un autre déplacement, utiliser la grille.</p>}
      </>}
      <button type="submit" disabled={busy || (mode === "future" &&
        (!draft.days_of_week.length || (!!source && !draft.target_days_of_week?.length)))}>
        {busy ? "Vérification…" : "Prévisualiser les conséquences"}
      </button>
    </form>}
    {error && <p role="alert" className="error">{error}</p>}
    {preview && <div className="eligPreview" aria-live="polite">
      <h5>Aperçu serveur · {preview.projection_days ?? "occurrence datée"}</h5>
      <p>Capacité physique : {preview.before_physical_minutes} → {preview.after_physical_minutes} min.
        Les permissions superposées ne s'additionnent pas.</p>
      {preview.consequences && <ul>{preview.consequences.map((item, i) => <li key={i}>{item}</li>)}</ul>}
      {!!preview.future_revisions_superseded?.length &&
        <p>Révisions futures remplacées : {preview.future_revisions_superseded.join(", ")}.</p>}
      {!preview.calendar_checked && <p>Google non vérifié : temps libre inconnu.</p>}
      {!!unresolved.length && <div>
        <h5>Décisions sur les exceptions futures</h5>
        {unresolved.map((exc) => <label key={exc.exception_id}>
          Exception {exc.exception_id.slice(0, 8)}
          <select defaultValue="" onChange={(event) => {
            const decisions = draft.exception_decisions.filter((v) => v.exception_id !== exc.exception_id);
            if (event.target.value) decisions.push({ exception_id: exc.exception_id,
              expected_version: exc.expected_version, action: event.target.value as "KEEP" | "DISABLE" });
            change({ exception_decisions: decisions });
          }}>
            <option value="">Choisir puis refaire l'aperçu</option>
            {exc.choices.filter((choice) => choice !== "REPLACE").map((choice) =>
              <option key={choice} value={choice}>{choice === "KEEP" ? "Conserver" : "Désactiver"}</option>)}
          </select></label>)}
      </div>}
      {!!preview.blocking_issues.length && <p role="alert" className="error">
        Conflits bloquants : {preview.blocking_issues.join(", ")}.</p>}
      {!!preview.booking_inventory.length && <label><input type="checkbox"
        checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
        Je reconnais que {preview.booking_inventory.length} réservation(s) confirmée(s) restent inchangées.</label>}
      <button type="button" disabled={busy || !!preview.blocking_issues.length ||
        (!!preview.booking_inventory.length && !acknowledged)} onClick={() => void confirm()}>
        Confirmer explicitement</button>
    </div>}
  </section>;
}
