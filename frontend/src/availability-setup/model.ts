// TP-026B0 — neutral view models. These are not backend DTOs or domain decisions.
export type ParentChoice = { id: string; label: string };
export type WorkTypeChoice = { id: string; parentId: string; label: string };

export type SetupProgress = {
  hasParent: boolean;
  hasWorkType: boolean;
  hasEnvelope: boolean;
  hasPermission: boolean;
};

export type WindowDraft = {
  parentId: string;
  workTypeId: string;
  daysOfWeek: number[];
  startTime: string;
  endTime: string;
  priority: string; // empty means neutral; keep text until validation
  timezone: string;
  effectiveDate: string;
};

// Contract handed to TP-026B's preview adapter, NEVER directly to an API.
export type WindowPreviewRequest = Omit<WindowDraft, "priority"> & {
  priority: number | null;
};

export type WindowField = keyof WindowDraft;
export type WindowErrors = Partial<Record<WindowField, string>>;

export const WEEKDAYS = [
  "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche",
] as const;

function validTime(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function validTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat("fr-CA", { timeZone: value });
    return Boolean(value.trim());
  } catch {
    return false;
  }
}

export function validateWindowDraft(
  draft: WindowDraft,
  parents: readonly ParentChoice[],
  workTypes: readonly WorkTypeChoice[],
  envelopeParentIds: readonly string[],
  minimumEffectiveDate: string,
): WindowErrors {
  const errors: WindowErrors = {};
  const parent = parents.find((item) => item.id === draft.parentId);
  if (!parent) errors.parentId = "Crée ou sélectionne une catégorie parente.";
  const workType = workTypes.find((item) => item.id === draft.workTypeId);
  if (!workType || !parent || workType.parentId !== parent.id)
    errors.workTypeId = "Choisis une sous-catégorie de ce parent.";
  if (parent && !envelopeParentIds.includes(parent.id))
    errors.parentId = "Définis l'enveloppe physique de ce parent avant l'aperçu.";
  if (draft.daysOfWeek.length === 0 ||
      new Set(draft.daysOfWeek).size !== draft.daysOfWeek.length ||
      draft.daysOfWeek.some((day) => !Number.isInteger(day) || day < 0 || day > 6))
    errors.daysOfWeek = "Choisis au moins un jour valide.";
  if (!validTime(draft.startTime)) errors.startTime = "Indique une heure de début valide.";
  if (!validTime(draft.endTime) ||
      (validTime(draft.startTime) && draft.endTime <= draft.startTime))
    errors.endTime = "L'heure de fin doit suivre le début, le même jour.";
  if (draft.priority !== "" &&
      (!/^[1-9]\d*$/.test(draft.priority) || !Number.isSafeInteger(Number(draft.priority))))
    errors.priority = "Indique un rang entier positif ou laisse vide (neutre).";
  if (!validTimezone(draft.timezone))
    errors.timezone = "Indique un fuseau IANA valide, par exemple America/Toronto.";
  if (!validDate(draft.effectiveDate) || !validDate(minimumEffectiveDate) ||
      draft.effectiveDate < minimumEffectiveDate)
    errors.effectiveDate = "Choisis une date d'effet valide à partir du minimum indiqué.";
  return errors;
}

export function toWindowPreviewRequest(draft: WindowDraft): WindowPreviewRequest {
  return {
    ...draft,
    daysOfWeek: [...draft.daysOfWeek].sort((a, b) => a - b),
    priority: draft.priority === "" ? null : Number(draft.priority),
  };
}
