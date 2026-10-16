import { type FormEvent, useEffect, useState } from "react";
import { apiFetch } from "./auth";

export type Scope = {
  id: string; name: string; version: number; state: "ACTIVE" | "INACTIVE";
  is_compatibility: boolean;
};
export type Affiliation = {
  work_type_id: string; scope_id: string; effective_from: string; version: number;
};
export type ScopeCatalog = {
  scopes: Scope[]; compatibility_scope_id: string; affiliations: Affiliation[];
  affiliation_versions: Record<string, number>; legacy_unassigned_work_type_ids: string[];
};
type WorkType = { id: string; name: string };
type RuleSource = { id: string; revisions: {
  kind: "GENERAL" | "CATEGORIZED"; scope_id?: string | null;
  work_type_id: string | null;
}[] };
type Conflict = {
  code: string; status: "NEW" | "PREEXISTING"; starts_at: string;
  ends_at: string; scope_ids: string[]; sources: string[];
};
type AffiliationPreview = {
  fingerprint: string; has_changes: boolean; projection_days: number;
  before_minutes_93d: Record<string, number>; after_minutes_93d: Record<string, number>;
  global_before_minutes_93d: number; global_after_minutes_93d: number;
  from_scope_id: string; to_scope_id: string; conflicts: Conflict[];
  civil_time_issues: { date: string; reason: string }[];
  unresolved_rule_migrations: { rule_id: string; reason: string }[];
  rules_inventory: { rule_id: string; revision: number; scope_id: string; explicitly_remapped: boolean }[];
  exceptions_inventory: { exception_id: string; action: string }[];
  manual_blocks_inventory: { block_id: string; starts_at: string }[];
  all_future_bookings: { booking_id: string; starts_at: string; scope_id: string | null }[];
};
type AffiliationDraft = {
  work_type_id: string; scope_id: string; effective_from: string; timezone_name: string;
  expected_affiliation_version: number; expected_scope_version: number; remap_rule_ids: string[];
};
type PreviewState = { draft: AffiliationDraft; snapshot: AffiliationPreview; commandId: string };

function tomorrowInZone(zone: string): string {
  const now = new Intl.DateTimeFormat("en-CA", { timeZone: zone,
    year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const part = (type: string) => now.find((value) => value.type === type)?.value || "";
  const date = new Date(part("year") + "-" + part("month") + "-" + part("day") + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

export function scopeForAt(workTypeId: string, date: string, catalog: ScopeCatalog): string {
  const matches = catalog.affiliations.filter((item) =>
    item.work_type_id === workTypeId && item.effective_from <= date)
    .sort((a, b) => a.effective_from.localeCompare(b.effective_from) || a.version - b.version);
  return matches.length ? matches[matches.length - 1].scope_id : catalog.compatibility_scope_id;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const value = await response.json().catch(() => null);
    throw new Error((response.status === 409 ? "Conflit de version (409). Actualise puis prévisualise à nouveau. " : "") +
      (typeof value?.detail === "string" ? value.detail : "Erreur HTTP " + response.status));
  }
  return response.json() as Promise<T>;
}

const headers = { "Content-Type": "application/json" };

export function ScheduleCategories({ catalog, workTypes, ruleSources, zone, onChanged, onWorkTypesChanged,
  onSelectScope }: {
  catalog: ScopeCatalog; workTypes: WorkType[]; ruleSources: RuleSource[]; zone: string;
  onChanged: () => Promise<void>; onWorkTypesChanged: () => Promise<void>;
  onSelectScope: (id: string) => void;
}) {
  const [newScope, setNewScope] = useState("");
  const [newLeaf, setNewLeaf] = useState("");
  const [leafParent, setLeafParent] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [workTypeId, setWorkTypeId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(() => tomorrowInZone(zone));
  const [remapRules, setRemapRules] = useState<string[]>([]);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const minimum = tomorrowInZone(zone);
  useEffect(() => { setPreview(null); setAcknowledge(false); }, [zone]);
  const allScopes = [ ...catalog.scopes.filter((scope) => !scope.is_compatibility),
    ...catalog.scopes.filter((scope) => scope.is_compatibility) ];
  const scopeLabel = (id: string) =>
    id === catalog.compatibility_scope_id ? "Compatibilité (héritage)" :
      catalog.scopes.find((scope) => scope.id === id)?.name || id.slice(0, 8);
  const currentScope = workTypeId ? scopeForAt(workTypeId, effectiveFrom, catalog) : "";
  const candidateRules = ruleSources.filter((rule) => rule.revisions.some((revision) =>
    (revision.kind === "CATEGORIZED" && revision.work_type_id === workTypeId) ||
    (revision.kind === "GENERAL" && !revision.scope_id)));
  const activeScopes = catalog.scopes.filter((scope) => scope.state === "ACTIVE" && !scope.is_compatibility);
  function invalidate() { setPreview(null); setAcknowledge(false); setNotice(""); }

  async function operate(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); await onChanged(); invalidate(); setNotice(success); }
    catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Opération impossible.";
      setError(message);
      if (message.includes("(409)")) {
        setPreview(null); setAcknowledge(false);
        await onChanged().catch(() => undefined);
      }
    } finally { setBusy(false); }
  }

  async function createParent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newScope.trim()) return;
    await operate(async () => {
      const created = await request<Scope>("/api/schedule-scopes", {
        method: "POST", headers, body: JSON.stringify({ name: newScope.trim() }),
      });
      setNewScope("");
      onSelectScope(created.id);
    }, "Catégorie parente créée. Son enveloppe peut maintenant être configurée.");
  }
  async function saveParent(scope: Scope, state: "ACTIVE" | "INACTIVE", name: string) {
    if (state === "INACTIVE" && !window.confirm(
      "Désactiver cette catégorie seulement si aucune feuille ou règle ne lui est rattachée ?")) return;
    await operate(async () => {
      await request("/api/schedule-scopes/" + scope.id, {
        method: "PATCH", headers, body: JSON.stringify({
          name: name.trim(), state, expected_version: scope.version,
        }),
      });
      setRenaming(null);
    }, state === "INACTIVE" ? "Catégorie désactivée." : "Catégorie mise à jour.");
  }
  async function createLeaf(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newLeaf.trim() || !leafParent) return;
    await operate(async () => {
      const created = await request<WorkType>("/api/work-types", {
        method: "POST", headers, body: JSON.stringify({ name: newLeaf.trim() }),
      });
      // TP-024A intentionally creates leaves in compatibility first.
      // Their requested parent is effective only after preview + confirmation.
      await onWorkTypesChanged();
      setWorkTypeId(created.id); setTargetId(leafParent);
      setNewLeaf(""); setRemapRules([]);
    }, "Sous-catégorie créée en compatibilité. Prévisualise et confirme son rattachement daté ci-dessous.");
  }
  function draft(): AffiliationDraft {
    const selected = catalog.scopes.find((scope) => scope.id === targetId);
    if (!selected || selected.state !== "ACTIVE")
      throw new Error("Choisis une catégorie parente active.");
    return {
      work_type_id: workTypeId, scope_id: targetId, effective_from: effectiveFrom,
      timezone_name: zone,
      expected_affiliation_version: catalog.affiliation_versions[workTypeId] ?? 0,
      expected_scope_version: selected.version, remap_rule_ids: remapRules,
    };
  }
  async function previewAffiliation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(""); invalidate();
    try {
      const payload = draft();
      const snapshot = await request<AffiliationPreview>("/api/schedule-scopes/affiliations/preview", {
        method: "POST", headers, body: JSON.stringify(payload),
      });
      setPreview({ draft: payload, snapshot, commandId: crypto.randomUUID() });
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Aperçu impossible.");
    } finally { setBusy(false); }
  }
  const blocked = preview !== null && (
    preview.snapshot.conflicts.some((row) => row.status === "NEW") ||
    preview.snapshot.civil_time_issues.length > 0 ||
    preview.snapshot.unresolved_rule_migrations.length > 0 ||
    preview.snapshot.exceptions_inventory.length > 0 ||
    preview.snapshot.manual_blocks_inventory.length > 0);
  async function confirmAffiliation() {
    if (!preview || busy || blocked || !preview.snapshot.has_changes ||
      (preview.snapshot.all_future_bookings.length > 0 && !acknowledge)) return;
    if (!window.confirm("Confirmer ce rattachement à la date choisie ? Les réservations CONFIRMED restent inchangées.")) return;
    const copy = preview;
    await operate(async () => {
      await request("/api/schedule-scopes/affiliations/confirm", {
        method: "POST", headers, body: JSON.stringify({ ...copy.draft,
          command_id: copy.commandId, fingerprint: copy.snapshot.fingerprint,
          confirmed: true, acknowledge_bookings: acknowledge,
        }),
      });
      setRemapRules([]);
    }, "Rattachement futur confirmé atomiquement. Aucune réservation ni événement Google déplacé.");
  }

  return <section className="availabilityCard scopeManager" aria-label="Catégories hiérarchiques">
    <h3>Catégories parentes et sous-catégories</h3>
    <p className="muted">Chaque parent possède sa propre enveloppe générale. Les sous-catégories partagent
      cette capacité, sans l'ajouter une seconde fois. Le contexte de compatibilité garde les anciennes données.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="availabilityNotice">{notice}</p>}
    <div className="scopeCards">
      {allScopes.map((scope) => <div className="scopeCard" key={scope.id}>
        <div className="scopeCardHead"><strong>{scope.is_compatibility ? "Compatibilité (héritage)" : scope.name}</strong>
          <small>{scope.state === "ACTIVE" ? "Active" : "Désactivée"}</small></div>
        <ul>{workTypes.filter((type) => scopeForAt(type.id, effectiveFrom, catalog) === scope.id)
          .map((type) => <li key={type.id}>{type.name}</li>)}</ul>
        {!workTypes.some((type) => scopeForAt(type.id, effectiveFrom, catalog) === scope.id) &&
          <p className="muted">Aucune sous-catégorie à cette date.</p>}
        {scope.is_compatibility ? <p className="muted">Données non reclassées; aucune conversion automatique.</p> :
          <div className="availabilityActions">
            <button type="button" onClick={() => onSelectScope(scope.id)} disabled={busy || scope.state !== "ACTIVE"}>
              Modifier l'enveloppe</button>
            <button type="button" disabled={busy} onClick={() => {
              setRenaming(scope.id); setNewName(scope.name);
            }}>Renommer</button>
            {scope.state === "ACTIVE" &&
              <button type="button" disabled={busy} onClick={() => void saveParent(scope, "INACTIVE", scope.name)}>
                Désactiver</button>}
          </div>}
        {renaming === scope.id && <form className="scopeInlineForm" onSubmit={(event) => {
          event.preventDefault(); void saveParent(scope, scope.state, newName);
        }}><label>Nouveau nom<input maxLength={200} required value={newName}
          onChange={(event) => setNewName(event.target.value)} /></label>
          <button disabled={busy || !newName.trim()}>Enregistrer</button>
          <button type="button" onClick={() => setRenaming(null)}>Annuler</button></form>}
      </div>)}
    </div>
    <div className="scopeForms">
      <form onSubmit={(event) => void createParent(event)}>
        <h4>Nouvelle catégorie parente</h4>
        <label>Nom<input maxLength={200} required value={newScope}
          onChange={(event) => setNewScope(event.target.value)} placeholder="Travail, Personnel…" /></label>
        <button disabled={busy || !newScope.trim()}>Créer le parent</button>
      </form>
      <form onSubmit={(event) => void createLeaf(event)}>
        <h4>Nouvelle sous-catégorie</h4>
        <label>Nom<input maxLength={200} required value={newLeaf}
          onChange={(event) => setNewLeaf(event.target.value)} placeholder="Focus, Famille…" /></label>
        <label>Parent souhaité<select required value={leafParent}
          onChange={(event) => setLeafParent(event.target.value)}>
          <option value="">Choisir un parent</option>
          {activeScopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.name}</option>)}
        </select></label>
        <button disabled={busy || !newLeaf.trim() || !leafParent}>Créer puis rattacher</button>
        <small>La création n'affecte pas la catégorie : l'étape de rattachement doit être confirmée.</small>
      </form>
    </div>
    <form className="scopeAffiliation" onSubmit={(event) => void previewAffiliation(event)}>
      <h4>Rattacher ou reclasser une sous-catégorie (avec aperçu)</h4>
      <div className="availabilityFields">
        <label>Sous-catégorie<select required value={workTypeId} onChange={(event) => {
          setWorkTypeId(event.target.value); setRemapRules([]); invalidate();
        }}><option value="">Choisir…</option>{workTypes.map((type) =>
          <option key={type.id} value={type.id}>{type.name}</option>)}</select></label>
        <label>Catégorie cible<select required value={targetId} onChange={(event) => {
          setTargetId(event.target.value); invalidate();
        }}><option value="">Choisir…</option>{catalog.scopes.filter((s) => s.state === "ACTIVE")
          .map((scope) => <option key={scope.id} value={scope.id}>{scopeLabel(scope.id)}</option>)}
        </select></label>
        <label>Date d'effet (IANA {zone})<input type="date" required min={minimum}
          value={effectiveFrom} onChange={(event) => {
            setEffectiveFrom(event.target.value); setRemapRules([]); invalidate();
          }} /></label>
      </div>
      {workTypeId && <p className="muted">Appartenance actuelle à cette date :
        {" "}<strong>{scopeLabel(currentScope)}</strong>. UUID de la feuille conservé.
        Une nouvelle affectation ne réécrit jamais l'historique passé.</p>}
      {workTypeId && candidateRules.length > 0 && <fieldset className="scopeRemaps">
        <legend>Séries à migrer explicitement (aucun transfert implicite)</legend>
        {candidateRules.map((rule) => <label key={rule.id}><input type="checkbox"
          checked={remapRules.includes(rule.id)} onChange={(event) => {
            setRemapRules((old) => event.target.checked ? [...old, rule.id] :
              old.filter((id) => id !== rule.id)); invalidate();
          }} /> Règle {rule.id.slice(0, 8)}
          {rule.revisions.some((rev) => rev.kind === "GENERAL" && !rev.scope_id) ?
            " · ancienne enveloppe générale (à déplacer seulement si voulu)" : " · plages de cette feuille"}
        </label>)}
      </fieldset>}
      <button disabled={busy || !workTypeId || !targetId || effectiveFrom < minimum}>
        Prévisualiser le rattachement</button>
    </form>
    {preview && <div className="availabilityPreview scopePreview" aria-live="polite">
      <h4>Aperçu serveur du reclassement — aucune écriture</h4>
      <p>Projection limitée à {preview.snapshot.projection_days} jours civils; Google non vérifié.
        Les autres périodes futures ne sont pas supposées exemptes de conflits.</p>
      <p><strong>{scopeLabel(preview.snapshot.from_scope_id)}</strong> →
        {" "}<strong>{scopeLabel(preview.snapshot.to_scope_id)}</strong> à partir du {effectiveFrom}.</p>
      <p>Total déclaré (minutes physiques uniques) :
        {" "}{preview.snapshot.global_before_minutes_93d} → {preview.snapshot.global_after_minutes_93d} min.</p>
      <ul>{Array.from(new Set([...Object.keys(preview.snapshot.before_minutes_93d),
        ...Object.keys(preview.snapshot.after_minutes_93d)])).map((id) =>
        <li key={id}>{scopeLabel(id)} :
          {" "}{preview.snapshot.before_minutes_93d[id] || 0} →
          {" "}{preview.snapshot.after_minutes_93d[id] || 0} min</li>)}</ul>
      {preview.snapshot.conflicts.length > 0 && <div className="scopeDiagnostics">
        <strong>Incompatibilités : {preview.snapshot.conflicts.length}</strong>
        <ul>{preview.snapshot.conflicts.map((issue, index) => <li key={index}>
          {issue.status === "NEW" ? "Nouveau — bloquant" : "Préexistant"} · {issue.code} ·
          {" "}{issue.starts_at}–{issue.ends_at} ·
          {" "}{issue.scope_ids.map(scopeLabel).join(" / ")}
          <small>Sources : {issue.sources.join(", ")}</small>
        </li>)}</ul>
      </div>}
      {preview.snapshot.unresolved_rule_migrations.length > 0 && <p role="alert" className="error">
        {preview.snapshot.unresolved_rule_migrations.length} série(s) futures à réconcilier
        explicitement avant confirmation. Modifie la sélection puis refais l'aperçu.</p>}
      {(preview.snapshot.exceptions_inventory.length > 0 || preview.snapshot.manual_blocks_inventory.length > 0) &&
        <p role="alert" className="error">Exceptions ou blocs manuels impactés :
          le serveur exige une résolution explicite avant ce reclassement.</p>}
      {preview.snapshot.civil_time_issues.map((issue, i) => <p key={i} role="alert" className="error">
        {issue.date} : {issue.reason}</p>)}
      <p>{preview.snapshot.rules_inventory.length} révision(s) de règles inventoriées,
        {" "}{preview.snapshot.all_future_bookings.length} réservation(s) futures conservées,
        {" "}{preview.snapshot.exceptions_inventory.length} exception(s) impactées.</p>
      {preview.snapshot.all_future_bookings.length > 0 && <><ul>
        {preview.snapshot.all_future_bookings.map((booking) =>
          <li key={booking.booking_id}>Réservation {booking.booking_id.slice(0, 8)} ·
            {" "}{booking.starts_at} · provenance {booking.scope_id ? scopeLabel(booking.scope_id) : "inconnue"}</li>)}
        </ul><label className="weeklyAcknowledgment"><input type="checkbox" checked={acknowledge}
          onChange={(event) => setAcknowledge(event.target.checked)} />
          Je reconnais que ces réservations CONFIRMED restent inchangées, même en conflit.
        </label></>}
      {!preview.snapshot.has_changes && <p>Aucun changement à confirmer.</p>}
      <div className="availabilityActions">
        <button type="button" onClick={() => void confirmAffiliation()} disabled={busy || !!blocked ||
          !preview.snapshot.has_changes ||
          (preview.snapshot.all_future_bookings.length > 0 && !acknowledge)}>
          Confirmer le rattachement futur</button>
        <button type="button" onClick={() => setPreview(null)}>Retour au brouillon</button>
      </div>
    </div>}
  </section>;
}
