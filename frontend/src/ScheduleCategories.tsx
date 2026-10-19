import { useState, type FormEvent } from "react";
import { apiFetch } from "./auth";

export type Scope = {
  id: string; name: string; version: number; state: "ACTIVE" | "INACTIVE";
};
export type ScopeCatalog = { scopes: Scope[] };
type WorkType = { id: string; name: string; scope_id: string };

const headers = { "Content-Type": "application/json" };

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error((typeof body?.detail === "string" ? body.detail : "Erreur HTTP " + response.status) +
      " (" + response.status + ")");
  }
  return response.json() as Promise<T>;
}

/** TP-026B: every new activity is created directly in its immutable real parent. */
export function ScheduleCategories({ catalog, workTypes, onChanged, onWorkTypesChanged,
  onSelectScope }: {
  catalog: ScopeCatalog; workTypes: WorkType[];
  onChanged: () => Promise<void>; onWorkTypesChanged: () => Promise<void>;
  onSelectScope: (id: string) => void;
}) {
  const [newScope, setNewScope] = useState("");
  const [newLeaf, setNewLeaf] = useState("");
  const [leafParent, setLeafParent] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeScopes = catalog.scopes.filter((scope) => scope.state === "ACTIVE");

  async function operate(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      await action();
      await onChanged();
      setNotice(success);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Opération impossible.");
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
      setLeafParent(created.id);
      onSelectScope(created.id);
    }, "Parent créé. Définis son enveloppe physique avant d'ajouter une permission.");
  }
  async function createLeaf(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newLeaf.trim() || !leafParent) return;
    await operate(async () => {
      await request("/api/work-types", {
        method: "POST", headers, body: JSON.stringify({
          name: newLeaf.trim(), scope_id: leafParent,
        }),
      });
      setNewLeaf("");
      await onWorkTypesChanged();
      onSelectScope(leafParent);
    }, "Sous-catégorie directement rattachée à son parent.");
  }
  async function saveParent(scope: Scope, state: Scope["state"], name: string) {
    if (state === "INACTIVE" && !window.confirm(
      "Désactiver ce parent ? Le serveur refusera s'il contient des activités ou des plages.")) return;
    await operate(async () => {
      await request("/api/schedule-scopes/" + scope.id, {
        method: "PATCH", headers, body: JSON.stringify({
          name: name.trim(), state, expected_version: scope.version,
        }),
      });
      setRenaming(null);
    }, state === "INACTIVE" ? "Parent désactivé." : "Parent mis à jour.");
  }

  return <section id="availability-categories" className="availabilityCard scopeManager"
    aria-label="Catégories hiérarchiques">
    <h3>Catégories parentes et sous-catégories</h3>
    <p className="muted">Chaque activité appartient directement à un parent. Ses permissions peuvent
      chevaucher celles des autres activités du même parent, sans doubler la capacité physique.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {notice && <p role="status" className="availabilityNotice">{notice}</p>}
    {catalog.scopes.length === 0 && <p className="empty">Aucune catégorie créée. Commence par un parent.</p>}
    <div className="scopeCards">
      {catalog.scopes.map((scope) => <div className="scopeCard" key={scope.id}>
        <div className="scopeCardHead">
          <strong>{scope.name}</strong>
          <small>{scope.state === "ACTIVE" ? "Active" : "Désactivée"}</small>
        </div>
        <ul>{workTypes.filter((type) => type.scope_id === scope.id).map((type) =>
          <li key={type.id}>{type.name}</li>)}</ul>
        {!workTypes.some((type) => type.scope_id === scope.id) &&
          <p className="muted">Aucune sous-catégorie.</p>}
        <div className="availabilityActions">
          <button type="button" disabled={busy || scope.state !== "ACTIVE"}
            onClick={() => onSelectScope(scope.id)}>Configurer l'enveloppe</button>
          <button type="button" disabled={busy} onClick={() => {
            setRenaming(scope.id); setNewName(scope.name);
          }}>Renommer</button>
          {scope.state === "ACTIVE" &&
            <button type="button" disabled={busy} onClick={() =>
              void saveParent(scope, "INACTIVE", scope.name)}>Désactiver</button>}
        </div>
        {renaming === scope.id && <form className="scopeInlineForm" onSubmit={(event) => {
          event.preventDefault(); void saveParent(scope, scope.state, newName);
        }}>
          <label>Nouveau nom<input maxLength={200} required value={newName}
            onChange={(event) => setNewName(event.target.value)} /></label>
          <button disabled={busy || !newName.trim()}>Enregistrer</button>
          <button type="button" onClick={() => setRenaming(null)}>Annuler</button>
        </form>}
      </div>)}
    </div>
    <div className="scopeForms">
      <form onSubmit={(event) => void createParent(event)}>
        <h4>Nouvelle catégorie parente</h4>
        <label>Nom<input id="tp26-new-parent" maxLength={200} required value={newScope}
          onChange={(event) => setNewScope(event.target.value)}
          placeholder="Travail, Personnel…" /></label>
        <button disabled={busy || !newScope.trim()}>Créer le parent</button>
      </form>
      <form onSubmit={(event) => void createLeaf(event)}>
        <h4>Nouvelle sous-catégorie</h4>
        <label>Nom<input id="tp26-new-work-type" maxLength={200} required value={newLeaf}
          onChange={(event) => setNewLeaf(event.target.value)}
          placeholder="Focus work, Réunions…" /></label>
        <label>Catégorie parente<select required value={leafParent}
          onChange={(event) => setLeafParent(event.target.value)}>
          <option value="">Choisir un parent</option>
          {activeScopes.map((scope) => <option key={scope.id} value={scope.id}>{scope.name}</option>)}
        </select></label>
        <button disabled={busy || !newLeaf.trim() || !leafParent}>Ajouter la sous-catégorie</button>
      </form>
    </div>
  </section>;
}
