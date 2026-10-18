import { useState, type FormEvent } from "react";
import {
  WEEKDAYS, toWindowPreviewRequest, validateWindowDraft,
  type ParentChoice, type SetupProgress, type WindowDraft,
  type WindowErrors, type WindowPreviewRequest, type WorkTypeChoice,
} from "./model";
import "./availability-setup.css";

type GuideActions = {
  onCreateParent: () => void;
  onAddWorkType: () => void;
  onDefineEnvelope: () => void;
  onNewWindow: () => void;
};

export function AvailabilitySetupGuide({ progress, onCreateParent, onAddWorkType,
  onDefineEnvelope, onNewWindow }: { progress: SetupProgress } & GuideActions) {
  const steps = [
    { label: "Créer une catégorie parente", complete: progress.hasParent,
      enabled: true, action: onCreateParent },
    { label: "Ajouter une sous-catégorie", complete: progress.hasWorkType,
      enabled: progress.hasParent, action: onAddWorkType },
    { label: "Définir l'enveloppe de travail", complete: progress.hasEnvelope,
      enabled: progress.hasParent && progress.hasWorkType, action: onDefineEnvelope },
  ];
  return <section className="tp26-guide" aria-label="Première configuration">
    <h2>Configurer mes disponibilités</h2>
    <p>Crée un parent, sa sous-catégorie et son enveloppe physique, puis ajoute une permission.
      Aucune catégorie n'est créée automatiquement.</p>
    <ol className="tp26-steps">
      {steps.map((step, index) => <li key={step.label}>
        <div><strong>{index + 1}. {step.label}</strong>
          <span>{step.complete ? "Terminé" : step.enabled ? "À configurer" : "Étape précédente requise"}</span></div>
        <button type="button" onClick={step.action} disabled={!step.enabled}>
          {step.complete ? "Gérer" : step.label}
        </button>
      </li>)}
      <li>
        <div><strong>4. Ajouter une première plage</strong>
          <span>{progress.hasPermission ? "Une permission existe" : "Accessible même sans barre dans la grille"}</span></div>
        <button type="button" onClick={onNewWindow}>+ Nouvelle plage</button>
      </li>
    </ol>
  </section>;
}

export function AvailabilityEmptyState() {
  return <section className="tp26-empty" aria-label="Grille de disponibilités vide">
    <h3>Aucune plage pour le moment</h3>
    <p>La grille est vide. Utilise « + Nouvelle plage » ci-dessus pour préparer ta
      première permission, même si aucune barre n'existe encore.</p>
  </section>;
}

export function NewAvailabilityWindowForm({ parents, workTypes, envelopeParentIds,
  initialTimezone, minimumEffectiveDate, onPreview, onCancel }: {
  parents: readonly ParentChoice[];
  workTypes: readonly WorkTypeChoice[];
  envelopeParentIds: readonly string[];
  initialTimezone: string;
  minimumEffectiveDate: string;
  onPreview: (draft: WindowPreviewRequest) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<WindowDraft>({
    parentId: "", workTypeId: "", daysOfWeek: [], startTime: "09:00",
    endTime: "12:00", priority: "", timezone: initialTimezone,
    effectiveDate: minimumEffectiveDate,
  });
  const [errors, setErrors] = useState<WindowErrors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const [notice, setNotice] = useState("");
  const choices = workTypes.filter((item) => item.parentId === draft.parentId);

  function change(patch: Partial<WindowDraft>) {
    setDraft((previous) => ({ ...previous, ...patch }));
    setErrors({}); setFailure(""); setNotice("");
  }
  function toggleDay(day: number, checked: boolean) {
    change({ daysOfWeek: checked ?
      [...draft.daysOfWeek.filter((item) => item !== day), day] :
      draft.daysOfWeek.filter((item) => item !== day) });
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const invalid = validateWindowDraft(draft, parents, workTypes,
      envelopeParentIds, minimumEffectiveDate);
    setErrors(invalid); setFailure(""); setNotice("");
    if (Object.keys(invalid).length) return;
    setBusy(true);
    try {
      await onPreview(toWindowPreviewRequest(draft));
      setNotice("Brouillon transmis pour aperçu. Aucune plage n'a été enregistrée.");
    } catch (reason: unknown) {
      setFailure(reason instanceof Error ? reason.message : "Aperçu indisponible.");
    } finally {
      setBusy(false);
    }
  }
  return <section className="tp26-form-card" aria-label="Formulaire nouvelle plage">
    <div className="tp26-form-header">
      <div><h3>+ Nouvelle plage</h3>
        <p>Prépare une permission récurrente. L'aperçu et la confirmation finale
          seront pris en charge par l'étape d'intégration.</p></div>
      <button type="button" className="tp26-secondary" onClick={onCancel} disabled={busy}>
        Fermer
      </button>
    </div>
    <form onSubmit={(event) => void submit(event)} noValidate>
      <div className="tp26-fields">
        <label>Catégorie parente
          <select value={draft.parentId} aria-invalid={Boolean(errors.parentId)}
            onChange={(event) => change({ parentId: event.target.value, workTypeId: "" })}>
            <option value="">Choisir un parent</option>
            {parents.map((parent) => <option key={parent.id} value={parent.id}>{parent.label}</option>)}
          </select>
          {errors.parentId && <small className="tp26-error">{errors.parentId}</small>}
        </label>
        <label>Sous-catégorie
          <select value={draft.workTypeId} aria-invalid={Boolean(errors.workTypeId)}
            onChange={(event) => change({ workTypeId: event.target.value })}>
            <option value="">Choisir une sous-catégorie</option>
            {choices.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
          {errors.workTypeId && <small className="tp26-error">{errors.workTypeId}</small>}
        </label>
        <label>Heure de début
          <input type="time" value={draft.startTime} aria-invalid={Boolean(errors.startTime)}
            onChange={(event) => change({ startTime: event.target.value })} />
          {errors.startTime && <small className="tp26-error">{errors.startTime}</small>}
        </label>
        <label>Heure de fin
          <input type="time" value={draft.endTime} aria-invalid={Boolean(errors.endTime)}
            onChange={(event) => change({ endTime: event.target.value })} />
          {errors.endTime && <small className="tp26-error">{errors.endTime}</small>}
        </label>
        <label>Rang de priorité (facultatif)
          <input type="number" min="1" step="1" placeholder="Neutre" value={draft.priority}
            aria-invalid={Boolean(errors.priority)}
            onChange={(event) => change({ priority: event.target.value })} />
          {errors.priority && <small className="tp26-error">{errors.priority}</small>}
        </label>
        <label>Fuseau horaire IANA
          <input type="text" spellCheck={false} value={draft.timezone}
            aria-invalid={Boolean(errors.timezone)}
            onChange={(event) => change({ timezone: event.target.value })} />
          {errors.timezone && <small className="tp26-error">{errors.timezone}</small>}
        </label>
        <label>Date d'effet
          <input type="date" min={minimumEffectiveDate} value={draft.effectiveDate}
            aria-invalid={Boolean(errors.effectiveDate)}
            onChange={(event) => change({ effectiveDate: event.target.value })} />
          {errors.effectiveDate && <small className="tp26-error">{errors.effectiveDate}</small>}
        </label>
      </div>
      <fieldset className="tp26-days" aria-invalid={Boolean(errors.daysOfWeek)}>
        <legend>Jours récurrents</legend>
        <div>{WEEKDAYS.map((day, index) => <label key={day}>
          <input type="checkbox" checked={draft.daysOfWeek.includes(index)}
            onChange={(event) => toggleDay(index, event.target.checked)} />{day}
        </label>)}</div>
        {errors.daysOfWeek && <small className="tp26-error">{errors.daysOfWeek}</small>}
      </fieldset>
      <p className="tp26-hint">Les chevauchements, la capacité réelle, les conflits et les
        confirmations sont évalués côté serveur après l'intégration.</p>
      {Object.keys(errors).length > 0 && <p role="alert" className="tp26-error">
        Corrige les champs indiqués avant de demander l'aperçu.</p>}
      {failure && <p role="alert" className="tp26-error">{failure}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="tp26-actions">
        <button type="submit" disabled={busy}>{busy ? "Préparation…" : "Prévisualiser"}</button>
        <button type="button" className="tp26-secondary" disabled={busy} onClick={onCancel}>
          Annuler
        </button>
      </div>
    </form>
  </section>;
}

// This optional composition has no backend access and can be mounted by TP-026B.
// The parent retains sole authority over category/envelope updates and preview/confirmation.
export function FirstAvailabilitySetup({ progress, parents, workTypes, envelopeParentIds,
  initialTimezone, minimumEffectiveDate, onCreateParent, onAddWorkType, onDefineEnvelope,
  onPreviewWindow }: {
  progress: SetupProgress;
  parents: readonly ParentChoice[];
  workTypes: readonly WorkTypeChoice[];
  envelopeParentIds: readonly string[];
  initialTimezone: string;
  minimumEffectiveDate: string;
  onCreateParent: () => void;
  onAddWorkType: () => void;
  onDefineEnvelope: () => void;
  onPreviewWindow: (request: WindowPreviewRequest) => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  return <div className="tp26">
    <AvailabilitySetupGuide progress={progress} onCreateParent={onCreateParent}
      onAddWorkType={onAddWorkType} onDefineEnvelope={onDefineEnvelope}
      onNewWindow={() => setEditing(true)} />
    {!progress.hasPermission && <AvailabilityEmptyState />}
    {editing && <NewAvailabilityWindowForm parents={parents} workTypes={workTypes}
      envelopeParentIds={envelopeParentIds} initialTimezone={initialTimezone}
      minimumEffectiveDate={minimumEffectiveDate} onPreview={onPreviewWindow}
      onCancel={() => setEditing(false)} />}
  </div>;
}
