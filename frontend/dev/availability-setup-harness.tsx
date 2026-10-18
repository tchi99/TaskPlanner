// Standalone test fixture: no app screen, credentials, network or backend calls.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { FirstAvailabilitySetup } from "../src/availability-setup/FirstAvailabilitySetup";
import type { ParentChoice, WindowPreviewRequest, WorkTypeChoice } from
  "../src/availability-setup/model";
import "../src/app.css";

function Harness() {
  const [parents, setParents] = useState<ParentChoice[]>([]);
  const [workTypes, setWorkTypes] = useState<WorkTypeChoice[]>([]);
  const [envelopes, setEnvelopes] = useState<string[]>([]);
  const [preview, setPreview] = useState<WindowPreviewRequest | null>(null);
  return <div className="shell" style={{ width: "min(880px, calc(100% - 24px))", padding: "20px 0" }}>
    <FirstAvailabilitySetup progress={{
      hasParent: parents.length > 0, hasWorkType: workTypes.length > 0,
      hasEnvelope: envelopes.length > 0, hasPermission: false,
    }} parents={parents} workTypes={workTypes} envelopeParentIds={envelopes}
      initialTimezone="America/Toronto" minimumEffectiveDate="2026-10-19"
      onCreateParent={() => setParents([{ id: "work", label: "Travail" }])}
      onAddWorkType={() => setWorkTypes([{ id: "focus", parentId: "work", label: "Focus" }])}
      onDefineEnvelope={() => setEnvelopes(["work"])}
      onPreviewWindow={(draft) => setPreview(draft)} />
    {preview && <output aria-label="Aperçu local">Brouillon : {JSON.stringify(preview)}</output>}
  </div>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
