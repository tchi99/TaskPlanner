import { useEffect, useState } from "react";
import { apiFetch } from "./auth";
import "./weekly-schedule.css";

type WorkType = { id: string; name: string };
type Kind = "GENERAL" | "CATEGORIZED";
type Mode = "PROTECTED" | "PREFERRED";
type Slot = {
  id: string; starts_at_local: string; ends_at_local: string;
  mode: Mode | null; start_fold: number | null; end_fold: number | null;
  sources?: { rule_id: string; revision: number }[];
};
type Cell = { weekday: number; kind: Kind; work_type_id: string | null; slots: Slot[] };
type GridResponse = {
  effective_from: string; timezone_name: string; source_versions: Record<string, number>;
  sections: (Omit<Cell, "slots"> & { slots: Omit<Slot, "id">[] })[];
  future_revisions: { rule_id: string; number: number; effective_from: string }[];
};
type EditSection = { weekday: number; kind: Kind; work_type_id: string | null; slots: Omit<Slot, "id" | "sources">[] };
type EditPayload = {
  effective_from: string; timezone_name: string; sections: EditSection[];
  expected_versions: Record<string, number>;
  exception_decisions: { exception_id: string; expected_version: number; action: string; target_rule_id: string | null }[];
};
type Change = { section: string; before: Slot[]; after: Slot[];
  previous_future: { effective_from: string; slots: Slot[] }[] };
type ExceptionChoice = { exception_id: string; version: number; candidate_rule_ids: string[]; reason: string };
type Preview = {
  fingerprint: string; has_changes: boolean; changed_sections: string[];
  cell_changes: Change[]; series_cutovers: { rule_id: string; version: number; future_revisions_superseded: number[] }[];
  unresolved_exceptions: ExceptionChoice[];
  exception_remaps: { exception_id: string; action: string; target_rule_id: string | null }[];
  booking_conflicts: { booking_id: string; starts_at: string; new: boolean }[];
  invalid_conflicts: string[]; civil_time_issues: { date: string; reason: string }[];
  before_declared_minutes_93d: number; after_declared_minutes_93d: number;
  projection_days: number; calendar_verified: boolean;
};
type PreviewState = { result: Preview; payload: EditPayload; commandId: string };

const days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"];
const headers = { "Content-Type": "application/json" };

function civilDayInZone(zone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const part = (name: string) => parts.find((value) => value.type === name)?.value || "";
  return part("year") + "-" + part("month") + "-" + part("day");
}
function addCivilDays(iso: string, daysToAdd: number): string {
  const date = new Date(iso + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + daysToAdd);
  return date.toISOString().slice(0, 10);
}
function cellKey(kind: Kind, type: string | null, weekday: number): string {
  return kind + ":" + (type || "NULL") + ":" + weekday;
}
function fromServer(grid: GridResponse): Record<string, Slot[]> {
  const cells: Record<string, Slot[]> = {};
  for (const section of grid.sections) {
    const key = cellKey(section.kind, section.work_type_id, section.weekday);
    cells[key] = section.slots.map((slot) => ({ ...slot, id: crypto.randomUUID() }));
  }
  return cells;
}
function newSlot(kind: Kind): Slot {
  return { id: crypto.randomUUID(), starts_at_local: "09:00", ends_at_local: "10:00",
    mode: kind === "GENERAL" ? null : "PREFERRED", start_fold: null, end_fold: null };
}
function titleOf(key: string, types: WorkType[]): string {
  // Backend cell IDs are weekday:kind:work_type_id:timezone, unlike local draft keys.
  const parts = key.split(":");
  const type = parts[2] === "NULL" ? "Enveloppe générale" :
    types.find((item) => item.id === parts[2])?.name || "Type " + parts[2].slice(0, 8);
  return days[Number(parts[0])] + " · " + type;
}
function slotText(slot: Slot): string {
  return slot.starts_at_local + "–" + slot.ends_at_local +
    (slot.mode === "PROTECTED" ? " (protégée)" : slot.mode === "PREFERRED" ? " (préférentielle)" : "");
}
async function callApi<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : "Erreur HTTP " + response.status;
    throw new Error((response.status === 409 ? "Conflit de versions (409) : " : "") + detail);
  }
  return await response.json() as T;
}

export function WeeklyScheduleEditor({ workTypes, zone, onSaved, onDirtyChange }: {
  workTypes: WorkType[]; zone: string; onSaved: () => Promise<void>;
  onDirtyChange: (value: boolean) => void;
}) {
  const [effectiveFrom, setEffectiveFrom] = useState(() => addCivilDays(civilDayInZone(zone), 1));
  const [grid, setGrid] = useState<GridResponse | null>(null);
  const [cells, setCells] = useState<Record<string, Slot[]>>({});
  const [dirty, setDirty] = useState<string[]>([]);
  const [selectedType, setSelectedType] = useState("GENERAL");
  const [copySource, setCopySource] = useState(0);
  const [copyTargets, setCopyTargets] = useState<number[]>([]);
  const [preparedCopy, setPreparedCopy] = useState<number[] | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [unresolved, setUnresolved] = useState<ExceptionChoice[]>([]);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { onDirtyChange(dirty.length > 0); }, [dirty.length, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const kind: Kind = selectedType === "GENERAL" ? "GENERAL" : "CATEGORIZED";
  const typeId = kind === "GENERAL" ? null : selectedType;
  const minimum = addCivilDays(civilDayInZone(zone), 1);
  const keyFor = (day: number) => cellKey(kind, typeId, day);
  const slotsOf = (day: number) => cells[keyFor(day)] || [];

  function acceptSnapshot(snapshot: GridResponse, keepDraft: boolean) {
    const baseline = fromServer(snapshot);
    setGrid(snapshot);
    setCells(keepDraft ? { ...baseline, ...Object.fromEntries(dirty.map((key) =>
      [key, cells[key] || []])) } : baseline);
    if (!keepDraft) setDirty([]);
    // Remapped exception candidates are tied to the old server projection.
    setChoices({}); setUnresolved([]);
    setPreview(null); setPreparedCopy(null); setAcknowledged(false);
  }
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setPreview(null);
    const query = "?effective_from=" + encodeURIComponent(effectiveFrom) +
      "&timezone_name=" + encodeURIComponent(zone);
    void callApi<GridResponse>("/api/availability/weekly-schedule" + query)
      .then((snapshot) => { if (active) acceptSnapshot(snapshot, false); })
      .catch((reason: unknown) => {
        if (active) { setGrid(null); setError(reason instanceof Error ? reason.message : "Lecture impossible."); }
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // A changed date or timezone is a new projection, never a mutation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveFrom, zone]);

  function changeDate(value: string) {
    if (!value || value === effectiveFrom) return;
    if (dirty.length && !window.confirm("Abandonner le brouillon et lire la grille à cette autre date ?")) return;
    setEffectiveFrom(value); setNotice("");
  }
  function modify(day: number, slots: Slot[]) {
    const key = keyFor(day);
    setCells((previous) => ({ ...previous, [key]: slots }));
    setDirty((previous) => previous.includes(key) ? previous : [...previous, key]);
    setPreview(null); setUnresolved([]); setChoices({});
    setPreparedCopy(null); setAcknowledged(false); setNotice("");
  }
  function changeSlot(day: number, id: string, patch: Partial<Slot>) {
    modify(day, slotsOf(day).map((slot) => slot.id === id ? { ...slot, ...patch } : slot));
  }
  function copySelection() {
    if (!copyTargets.length) return;
    for (const day of copyTargets) {
      const key = keyFor(day);
      const duplicate = slotsOf(copySource).map((slot) => ({ ...slot, id: crypto.randomUUID() }));
      setCells((previous) => ({ ...previous, [key]: duplicate }));
      setDirty((previous) => previous.includes(key) ? previous : [...previous, key]);
    }
    setPreparedCopy(null); setPreview(null); setUnresolved([]); setChoices({});
    setAcknowledged(false); setNotice("Copie ajoutée au brouillon, non enregistrée. Prévisualise avant de confirmer.");
  }
  function payload(): EditPayload {
    return {
      effective_from: effectiveFrom, timezone_name: zone,
      sections: dirty.map((key) => {
        const [kindPart, typePart, dayPart] = key.split(":");
        return {
          weekday: Number(dayPart), kind: kindPart as Kind,
          work_type_id: typePart === "NULL" ? null : typePart,
          slots: (cells[key] || []).map((slot) => ({
            starts_at_local: slot.starts_at_local, ends_at_local: slot.ends_at_local,
            mode: slot.mode, start_fold: slot.start_fold, end_fold: slot.end_fold,
          })),
        };
      }),
      expected_versions: grid?.source_versions || {},
      exception_decisions: unresolved.flatMap((item) => {
        const choice = choices[item.exception_id];
        return choice ? [{
          exception_id: item.exception_id, expected_version: item.version,
          action: choice === "DISABLE" ? "DISABLE" : "REMAP",
          target_rule_id: choice === "DISABLE" ? null : choice,
        }] : [];
      }),
    };
  }
  async function readAgain(keepDraft: boolean) {
    setBusy(true); setError("");
    try {
      const query = "?effective_from=" + encodeURIComponent(effectiveFrom) +
        "&timezone_name=" + encodeURIComponent(zone);
      const snapshot = await callApi<GridResponse>("/api/availability/weekly-schedule" + query);
      acceptSnapshot(snapshot, keepDraft);
      setNotice(keepDraft ? "Versions actualisées. Le brouillon est conservé; refais l'aperçu." : "Grille actualisée.");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Actualisation impossible.");
    } finally { setBusy(false); }
  }
  async function previewDraft() {
    if (!dirty.length || busy) return;
    setBusy(true); setError(""); setNotice(""); setPreview(null); setAcknowledged(false);
    try {
      const draft = payload();
      const result = await callApi<Preview>("/api/availability/weekly-schedule/preview", {
        method: "POST", headers, body: JSON.stringify(draft),
      });
      setUnresolved(result.unresolved_exceptions);
      setPreview({ result, payload: draft, commandId: crypto.randomUUID() });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Aperçu impossible.");
    } finally { setBusy(false); }
  }
  async function confirmDraft() {
    if (!preview || busy || !preview.result.has_changes ||
      preview.result.unresolved_exceptions.length ||
      preview.result.invalid_conflicts.length || preview.result.civil_time_issues.length ||
      (preview.result.booking_conflicts.some((item) => item.new) && !acknowledged)) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const receipt = await callApi<{ applied: boolean; calendar_written: boolean }>(
        "/api/availability/weekly-schedule/confirm", {
          method: "POST", headers, body: JSON.stringify({
            ...preview.payload, fingerprint: preview.result.fingerprint,
            command_id: preview.commandId, confirmed: true, acknowledge_conflicts: acknowledged,
          }),
        });
      await readAgain(false);
      await onSaved();
      setNotice(receipt.applied ? "Horaire futur enregistré atomiquement; réservations conservées." :
        "Aucun changement à enregistrer.");
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Enregistrement impossible.";
      setError(message + " Le brouillon reste disponible.");
      if (message.includes("(409)")) setPreview(null);
    } finally { setBusy(false); }
  }

  return <section className="availabilityCard weeklyEditor" aria-label="Éditeur hebdomadaire">
    <div className="availabilityCardHeading">
      <div><h3>Grille de l'horaire habituel</h3>
        <p className="muted">Modifie les occurrences futures par jour et par type. La semaine réelle, les exceptions et les réservations restent distinctes.</p></div>
      <button type="button" disabled={busy || loading} onClick={() => {
        if (!dirty.length || window.confirm("Abandonner le brouillon et recharger l'horaire ?"))
          void readAgain(false);
      }}>Actualiser la grille</button>
    </div>
    <div className="weeklyControls">
      <label>Date d'effet de la grille
        <input type="date" min={minimum} value={effectiveFrom}
          onChange={(event) => changeDate(event.target.value)} />
      </label>
      <p>Fuseau IANA : <strong>{zone}</strong>. Au plus tôt demain ({minimum}).</p>
      <label>Section de l'horaire
        <select value={selectedType} onChange={(event) => {
          setSelectedType(event.target.value); setPreparedCopy(null);
        }}>
          <option value="GENERAL">Enveloppe générale (NULL)</option>
          {workTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
        </select>
      </label>
    </div>
    {loading && <p role="status">Lecture de l'horaire futur…</p>}
    {!loading && error && <p role="status" className="error">{error}</p>}
    {notice && <p role="status" className="availabilityNotice">{notice}</p>}
    {!loading && grid && <>
      <p className="muted">{kind === "GENERAL" ?
        "L'enveloppe définit le temps admissible non catégorisé; les trous restent indisponibles." :
        "Chaque plage a son propre mode. Retirer une catégorie restitue NULL seulement sous l'enveloppe générale."}
      </p>
      <div className="weeklyDays" aria-label="Grille habituelle du lundi au dimanche">
        {days.map((dayName, day) => {
          const daySlots = slotsOf(day);
          const active = daySlots.length > 0;
          return <div className="weeklyDay" key={day}>
            <div className="weeklyDayHead">
              <label><input type="checkbox" checked={active} disabled={busy}
                onChange={(event) => modify(day, event.target.checked ? [newSlot(kind)] : [])} />
                <strong>{dayName}</strong></label>
              {dirty.includes(keyFor(day)) && <small>Modifié</small>}
            </div>
            {daySlots.map((slot, index) => <div className="weeklyInterval" key={slot.id}>
              <div className="weeklyTimeFields">
                <label>Début {index + 1}
                  <input aria-label={dayName + " plage " + (index + 1) + " début"} type="time"
                    step={60} value={slot.starts_at_local} disabled={busy}
                    onChange={(event) => changeSlot(day, slot.id, { starts_at_local: event.target.value })} />
                </label>
                <label>Fin {index + 1}
                  <input aria-label={dayName + " plage " + (index + 1) + " fin"} type="time"
                    step={60} value={slot.ends_at_local} disabled={busy}
                    onChange={(event) => changeSlot(day, slot.id, { ends_at_local: event.target.value })} />
                </label>
              </div>
              {kind === "CATEGORIZED" && <label>Mode
                <select aria-label={dayName + " plage " + (index + 1) + " mode"}
                  value={slot.mode || "PREFERRED"} disabled={busy}
                  onChange={(event) => changeSlot(day, slot.id, { mode: event.target.value as Mode })}>
                  <option value="PREFERRED">Préférentielle</option>
                  <option value="PROTECTED">Protégée</option>
                </select>
              </label>}
              <div className="weeklyIntervalBottom">
                <small className={"availabilityMode " + (slot.mode || "GENERAL")}>
                  {slot.mode === "PROTECTED" ? "Protégée" : slot.mode === "PREFERRED" ?
                    "Préférentielle" : "Générale"}</small>
                <button type="button" disabled={busy}
                  aria-label={"Retirer la plage " + (index + 1) + " du " + dayName}
                  onClick={() => modify(day, daySlots.filter((value) => value.id !== slot.id))}>− Retirer</button>
              </div>
              <details className="weeklyDst">
                <summary>Transitions DST · {slot.start_fold === null && slot.end_fold === null ?
                  "automatique" : "choix explicite"}</summary>
                <div className="weeklyTimeFields">
                  <label>Début (fold)
                    <select aria-label={dayName + " plage " + (index + 1) + " début DST"}
                      disabled={busy} value={slot.start_fold === null ? "" : String(slot.start_fold)}
                      onChange={(event) => changeSlot(day, slot.id, {
                        start_fold: event.target.value === "" ? null : Number(event.target.value),
                      })}>
                      <option value="">Automatique</option>
                      <option value="0">Premier instant</option><option value="1">Second instant</option>
                    </select>
                  </label>
                  <label>Fin (fold)
                    <select aria-label={dayName + " plage " + (index + 1) + " fin DST"}
                      disabled={busy} value={slot.end_fold === null ? "" : String(slot.end_fold)}
                      onChange={(event) => changeSlot(day, slot.id, {
                        end_fold: event.target.value === "" ? null : Number(event.target.value),
                      })}>
                      <option value="">Automatique</option>
                      <option value="0">Premier instant</option><option value="1">Second instant</option>
                    </select>
                  </label>
                </div>
              </details>
            </div>)}
            {!active && <p className="empty">Jour désactivé pour cette section.</p>}
            <button type="button" disabled={busy || daySlots.length >= 30}
              aria-label={"Ajouter une plage au " + dayName}
              onClick={() => modify(day, [...daySlots, newSlot(kind)])}>+ Ajouter une plage</button>
          </div>;
        })}
      </div>
      <section className="weeklyCopy" aria-label="Copier la journée">
        <h4>Copier une journée vers d'autres jours</h4>
        <div className="weeklyCopyControls">
          <label>Jour source<select value={copySource} disabled={busy} onChange={(event) => {
            setCopySource(Number(event.target.value)); setPreparedCopy(null);
            setCopyTargets([]);
          }}>{days.map((item, index) => <option value={index} key={item}>{item}</option>)}</select></label>
          <fieldset><legend>Jours destinataires</legend>
            {days.map((item, index) => index === copySource ? null :
              <label key={item}><input type="checkbox" checked={copyTargets.includes(index)} disabled={busy}
                onChange={(event) => {
                  setCopyTargets((prev) => event.target.checked ? [...prev, index] :
                    prev.filter((v) => v !== index));
                  setPreparedCopy(null);
                }} />{item}</label>)}
          </fieldset>
          <button type="button" disabled={busy} onClick={() => {
            setCopyTargets([0, 1, 2, 3, 4].filter((day) => day !== copySource));
            setPreparedCopy(null);
          }}>Jours ouvrables</button>
          <button type="button" disabled={busy || !copyTargets.length}
            onClick={() => setPreparedCopy([...copyTargets])}>Préparer la copie</button>
        </div>
        {preparedCopy && <div className="weeklyCopyPreview" aria-live="polite">
          <h4>Remplacements dans le brouillon (aucune sauvegarde)</h4>
          <p>Source : {days[copySource]} ({slotsOf(copySource).map(slotText).join(", ") || "jour désactivé"}).</p>
          <ul>{preparedCopy.map((day) => <li key={day}><strong>{days[day]}</strong> :
            {" "}{slotsOf(day).map(slotText).join(", ") || "jour désactivé"} →
            {" "}{slotsOf(copySource).map(slotText).join(", ") || "jour désactivé"}</li>)}</ul>
          <button type="button" disabled={busy} onClick={copySelection}>Appliquer la copie au brouillon</button>
          <button type="button" disabled={busy} onClick={() => setPreparedCopy(null)}>Annuler la copie</button>
        </div>}
      </section>
      <div className="weeklyFooter">
        <p><strong>{dirty.length} jour(s)/section(s) modifié(s)</strong> ·
          seuls ces cellules seront envoyées au serveur. Les autres dates, jours et types ne changent pas.</p>
        <button type="button" disabled={busy || !dirty.length} onClick={() => void previewDraft()}>
          {busy ? "Traitement…" : "Prévisualiser les changements"}</button>
        <button type="button" disabled={busy || !dirty.length} onClick={() => acceptSnapshot(grid, false)}>
          Annuler les modifications</button>
      </div>
      {unresolved.length > 0 && <div className="weeklyDecisions" aria-live="polite">
        <h4>Arbitrage des exceptions futures requis</h4>
        {unresolved.map((item) => <label key={item.exception_id}>
          Exception {item.exception_id.slice(0, 8)} (version {item.version})
          <select value={choices[item.exception_id] || ""} onChange={(event) => {
            setChoices((previous) => ({ ...previous, [item.exception_id]: event.target.value }));
            setPreview(null);
          }}>
            <option value="">Décision explicite requise…</option>
            <option value="DISABLE">Désactiver cette exception future</option>
            {item.candidate_rule_ids.map((id) => <option key={id} value={id}>
              Rattacher à la règle {id.slice(0, 8)}</option>)}
          </select>
        </label>)}
        <p className="muted">Choisir les arbitrages, puis refaire l'aperçu avant toute confirmation.</p>
      </div>}
      {preview && <div className="availabilityPreview weeklyPreview" aria-live="polite">
        <h4>Aperçu serveur : aucun changement encore enregistré</h4>
        <p>Capacité déclarée sur {preview.result.projection_days} jours :
          {" "}{preview.result.before_declared_minutes_93d} → {preview.result.after_declared_minutes_93d} minutes.
          Google Calendar non vérifié; aucune disponibilité libre garantie.</p>
        {preview.result.changed_sections.length === 0 ?
          <p>La grille correspond déjà à l'horaire demandé.</p> :
          <ul>{preview.result.cell_changes.map((item) => <li key={item.section}>
            <strong>{titleOf(item.section, workTypes)}</strong> :
            {" "}{item.before.map(slotText).join(", ") || "désactivé"} →
            {" "}{item.after.map(slotText).join(", ") || "désactivé"}
            {item.previous_future.length > 0 && <p>
              {item.previous_future.length} changement(s) futur(s) précédemment programmés seront remplacés.</p>}
          </li>)}</ul>}
        <p>{preview.result.series_cutovers.length} série(s) divisée(s)/terminée(s) ·
          {" "}{preview.result.exception_remaps.length} exception(s) réconciliée(s).</p>
        {preview.result.booking_conflicts.length > 0 && <div>
          <h4>Réservations CONFIRMED : conservées</h4>
          <ul>{preview.result.booking_conflicts.map((item) => <li key={item.booking_id}>
            {item.booking_id.slice(0, 8)} · {item.starts_at} ·
            {item.new ? " nouveau conflit" : " conflit déjà ouvert"}
          </li>)}</ul>
          {preview.result.booking_conflicts.some((item) => item.new) && <label className="weeklyAcknowledgment">
            <input type="checkbox" checked={acknowledged} onChange={(event) =>
              setAcknowledged(event.target.checked)} />
            Je reconnais les nouveaux conflits sans annuler ni déplacer les réservations.
          </label>}
        </div>}
        {preview.result.invalid_conflicts.map((issue) => <p key={issue} className="error">{issue}</p>)}
        {preview.result.civil_time_issues.map((issue, index) =>
          <p key={index} className="error">{issue.date} : {issue.reason}</p>)}
        {preview.result.unresolved_exceptions.length > 0 &&
          <p className="error">Résoudre les exceptions ci-dessus et refaire l'aperçu.</p>}
        <div className="availabilityActions">
          <button type="button" disabled={busy || !preview.result.has_changes ||
            preview.result.unresolved_exceptions.length > 0 ||
            preview.result.invalid_conflicts.length > 0 ||
            preview.result.civil_time_issues.length > 0 ||
            (preview.result.booking_conflicts.some((item) => item.new) && !acknowledged)}
            onClick={() => void confirmDraft()}>Confirmer et enregistrer l'horaire futur</button>
          <button type="button" disabled={busy} onClick={() => setPreview(null)}>Retour au brouillon</button>
        </div>
      </div>}
      {dirty.length > 0 && <button type="button" disabled={busy}
        className="weeklyRefreshVersions" onClick={() => void readAgain(true)}>
        Réactualiser les versions sans perdre le brouillon
      </button>}
    </>}
  </section>;
}
