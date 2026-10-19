import { useEffect, useState, type FormEvent } from "react";
import { apiFetch } from "./auth";

type Revision = {
  effective_from: string; timezone_name: string; days_of_week: number[];
  starts_at_local: string; ends_at_local: string; priority_rank: number | null;
  enabled: boolean; start_fold: number | null; end_fold: number | null;
};
type Series = { id: string; version: number; revisions: Revision[] };
type Draft = {
  draft_id: string; series_id: string | null;
  scope_id: string; work_type_id: string; expected_version: number;
  effective_from: string; timezone_name: string;
  days_of_week: number[]; starts_at_local: string; ends_at_local: string;
  priority_rank: number | null; enabled: boolean; start_fold: number | null; end_fold: number | null;
};
type Preview = {
  fingerprint: string; blocking_issues: string[];
  booking_inventory: { id: string; starts_at: string; ends_at: string }[];
  before_physical_minutes: number; after_physical_minutes: number;
  calendar_checked: boolean; consequences: string[]; projection_days: number;
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

export function EligibilityContextEditor({ scopeId, workTypeId, zone, seriesId,
  selectedDate, onClose, onSaved }: {
  scopeId: string; workTypeId: string; zone: string;
  seriesId: string | null; selectedDate: string;
  onClose: () => void; onSaved: () => void;
}) {
  const minimum = nextCivilDay(zone);
  const [draft, setDraft] = useState<Draft>({
    draft_id: crypto.randomUUID(), series_id: seriesId,
    scope_id: scopeId, work_type_id: workTypeId, expected_version: 0,
    effective_from: selectedDate > minimum ? selectedDate : minimum,
    timezone_name: zone, days_of_week: [new Date(selectedDate + "T12:00:00Z").getUTCDay() === 0 ?
      6 : new Date(selectedDate + "T12:00:00Z").getUTCDay() - 1],
    starts_at_local: "09:00", ends_at_local: "12:00", priority_rank: null,
    enabled: true, start_fold: null, end_fold: null,
  });
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(!seriesId);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    if (!seriesId) return;
    let active = true;
    const path = root + "/series/" + seriesId;
    void request<Series>(path).then((result) => {
      if (!active) return;
      const revision = result.revisions[result.revisions.length - 1];
      setDraft((previous) => ({
        ...previous, expected_version: result.version,
        days_of_week: [...revision.days_of_week],
        starts_at_local: revision.starts_at_local, ends_at_local: revision.ends_at_local,
        priority_rank: revision.priority_rank,
        start_fold: revision.start_fold, end_fold: revision.end_fold,
        enabled: revision.enabled,
      }));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Lecture impossible.");
    }).finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, [seriesId]);

  function change(patch: Partial<Draft>) {
    setDraft((previous) => ({ ...previous, ...patch }));
    setPreview(null); setAcknowledged(false); setError(""); setNotice("");
  }
  async function showPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); setPreview(null);
    try {
      const value = await request<Preview>(root + "/preview", {
        method: "POST", headers, body: JSON.stringify(draft),
      });
      setPreview(value); setAcknowledged(false);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Aperçu impossible.");
    } finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview || preview.blocking_issues.length ||
      (preview.booking_inventory.length > 0 && !acknowledged)) return;
    if (!window.confirm("Confirmer cette modification future ? Aucune réservation et aucun événement Google ne seront déplacés.")) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await request(root + "/confirm", {
        method: "POST", headers, body: JSON.stringify({
          ...draft, command_id: draft.draft_id, fingerprint: preview.fingerprint,
          confirmed: true, acknowledge_bookings: acknowledged,
        }),
      });
      setNotice("Permission future enregistrée. Aucune réservation déplacée.");
      onSaved(); onClose();
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Confirmation impossible.";
      setError(message + " Le brouillon est conservé.");
      if (message.includes("(409)")) setPreview(null);
    } finally { setBusy(false); }
  }
  return <section className="eligEdit" aria-label="Édition contextuelle d'admissibilité">
    <div className="availabilityCardHeading">
      <div><h4>{seriesId ? "Modifier une permission partagée" : "Nouvelle permission partagée"}</h4>
        <p className="muted">Parent {scopeId} · activité {workTypeId} · {zone}.
          L'édition est future, versionnée et sans glisser-déposer.</p></div>
      <button type="button" onClick={onClose} disabled={busy}>Fermer l'éditeur</button>
    </div>
    {!loaded && <p role="status">Chargement de la version de la règle…</p>}
    {loaded && <form className="eligEditForm" onSubmit={(event) => void showPreview(event)}>
      <label>Date d'effet (future)
        <input type="date" min={minimum} required value={draft.effective_from}
          onChange={(event) => change({ effective_from: event.target.value })} />
      </label>
      <label>Début local
        <input type="time" required value={draft.starts_at_local}
          onChange={(event) => change({ starts_at_local: event.target.value })} />
      </label>
      <label>Fin locale
        <input type="time" required value={draft.ends_at_local}
          onChange={(event) => change({ ends_at_local: event.target.value })} />
      </label>
      <label>Rang contextuel (vide = neutre)
        <input type="number" min={1} value={draft.priority_rank ?? ""}
          onChange={(event) => change({ priority_rank: event.target.value ?
            Number(event.target.value) : null })} />
      </label>
      <fieldset><legend>Jours récurrents</legend>
        {days.map((day, index) => <label key={day}><input type="checkbox"
          checked={draft.days_of_week.includes(index)} onChange={(event) => change({
            days_of_week: event.target.checked ?
              [...draft.days_of_week, index].sort((a, b) => a - b) :
              draft.days_of_week.filter((value) => value !== index),
          })} />{day}</label>)}
      </fieldset>
      <label><input type="checkbox" checked={draft.enabled}
        onChange={(event) => change({ enabled: event.target.checked })} />
        Permission activée</label>
      <label>Instant ambigu DST — début
        <select value={draft.start_fold === null ? "" : String(draft.start_fold)}
          onChange={(event) => change({ start_fold: event.target.value === "" ? null :
            Number(event.target.value) })}>
          <option value="">Automatique si non ambigu</option><option value="0">Premier instant</option>
          <option value="1">Second instant</option>
        </select>
      </label>
      <label>Instant ambigu DST — fin
        <select value={draft.end_fold === null ? "" : String(draft.end_fold)}
          onChange={(event) => change({ end_fold: event.target.value === "" ? null :
            Number(event.target.value) })}>
          <option value="">Automatique si non ambigu</option><option value="0">Premier instant</option>
          <option value="1">Second instant</option>
        </select>
      </label>
      <button type="submit" disabled={busy || !draft.days_of_week.length}>
        {busy ? "Vérification…" : "Prévisualiser les conséquences"}
      </button>
    </form>}
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status">{notice}</p>}
    {preview && <div className="eligPreview" aria-live="polite">
      <h5>Aperçu · {preview.projection_days} jours</h5>
      <p>Capacité physique avant : {preview.before_physical_minutes} min ;
        après : {preview.after_physical_minutes} min. Les potentiels sont non additifs.</p>
      <ul>{preview.consequences.map((item) => <li key={item}>{item}</li>)}</ul>
      {!preview.calendar_checked && <p>Google non vérifié : aucune minute n'est déclarée libre par cet aperçu.</p>}
      {preview.blocking_issues.length > 0 && <p role="alert" className="error">Conflits bloquants :
        {" "}{preview.blocking_issues.join(", ")}. Corriger la configuration et refaire l'aperçu.</p>}
      {preview.booking_inventory.length > 0 && <label><input type="checkbox"
        checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
        Je reconnais que {preview.booking_inventory.length} réservation(s) future(s)
        CONFIRMED restent inchangées, y compris au-delà de l'horizon de 93 jours.</label>}
      <button type="button" disabled={busy || !!preview.blocking_issues.length ||
        (!!preview.booking_inventory.length && !acknowledged)}
        onClick={() => void confirm()}>Confirmer cette édition future</button>
    </div>}
  </section>;
}
