import type { ReactNode } from "react";

export type WorkspacePage = "today" | "inbox" | "tasks" | "projects" | "planning" | "weekly";

export const workspacePages: {
  id: WorkspacePage;
  title: string;
  shortTitle: string;
  subtitle: string;
}[] = [
  { id: "today", title: "Aujourd'hui", shortTitle: "Aujourd'hui", subtitle: "Ce qui compte maintenant, et les choix à faire pour la journée." },
  { id: "inbox", title: "Boîte de réception", shortTitle: "Inbox", subtitle: "Clarifier ce que tu as capturé, sans perdre tes idées." },
  { id: "tasks", title: "Mes tâches", shortTitle: "Tâches", subtitle: "Retrouver le travail, ses prochaines actions et ses segments." },
  { id: "projects", title: "Projets et organisation", shortTitle: "Projets", subtitle: "Organiser tes projets et les types de travail." },
  { id: "planning", title: "Planification", shortTitle: "Planifier", subtitle: "Vérifier la capacité et choisir des blocs réalistes." },
  { id: "weekly", title: "Revue hebdomadaire", shortTitle: "Revue", subtitle: "Repérer ce qui dérive et décider des ajustements." },
];

function PageIcon({ name }: { name: WorkspacePage }) {
  let drawing: ReactNode;
  switch (name) {
    case "today":
      drawing = <><rect x="3" y="3" width="18" height="18" rx="4" /><path d="m7 12 3 3 7-7" /></>;
      break;
    case "inbox":
      drawing = <><path d="M4 4h16v12l-3 4H7l-3-4V4Z" /><path d="M4 14h5l2 3h2l2-3h5" /></>;
      break;
    case "tasks":
      drawing = <><path d="M9 6h12M9 12h12M9 18h12" /><path d="m3 6 1.5 1.5L7 4m-4 8 1.5 1.5L7 10m-4 8 1.5 1.5L7 16" /></>;
      break;
    case "projects":
      drawing = <><rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="8" rx="2" /><rect x="3" y="13" width="8" height="8" rx="2" /><rect x="13" y="13" width="8" height="8" rx="2" /></>;
      break;
    case "planning":
      drawing = <><rect x="3" y="5" width="18" height="16" rx="3" /><path d="M7 3v4M17 3v4M3 10h18M8 15h3M15 15h2" /></>;
      break;
    case "weekly":
      drawing = <><path d="M4 7h16M4 12h16M4 17h10" /><circle cx="18" cy="17" r="3" /></>;
      break;
  }
  return <svg className="pageIcon" viewBox="0 0 24 24" width="20" height="20"
    fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true">{drawing}</svg>;
}

export function WorkspaceNav({
  current, onNavigate, inboxCount,
}: {
  current: WorkspacePage;
  onNavigate: (page: WorkspacePage) => void;
  inboxCount: number;
}) {
  return (
    <aside className="workspaceSidebar">
      <div className="workspaceBrand">
        <span className="brandSymbol" aria-hidden="true">T</span>
        <span><strong>TaskPlanner</strong><small>Mon espace de travail</small></span>
      </div>
      <div className="workspaceNavCaption">Navigation</div>
      <nav className="workspaceNav" aria-label="Navigation principale">
        {workspacePages.map((page) => (
          <button key={page.id} type="button"
            className={"workspaceNavButton" + (current === page.id ? " isActive" : "")}
            onClick={() => onNavigate(page.id)}
            aria-current={current === page.id ? "page" : undefined}>
            <PageIcon name={page.id} />
            <span className="navButtonLabel">
              <span className="navFullLabel">{page.title}</span>
              <span className="navShortLabel">{page.shortTitle}</span>
            </span>
            {page.id === "inbox" && inboxCount > 0 && <span className="navCount">{inboxCount}</span>}
          </button>
        ))}
      </nav>
      <div className="sidebarStatus">
        <span className="sidebarStatusDot" aria-hidden="true" />
        <span>Espace personnel</span>
      </div>
    </aside>
  );
}
