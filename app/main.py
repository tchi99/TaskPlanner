from fastapi import FastAPI
from app.server.capacity import router as capacity_router
from app.server.calendar import router as calendar_router
from app.server.time_blocks import router as time_blocks_router
from app.server.decomposition import router as decomposition_router
from app.server.arbitration import router as arbitration_router
from app.server.protection import router as protection_router
from app.server.planning import router as planning_router
from app.server.morning import router as morning_router

from app.server.tasks import router as tasks_router
from app.server.projects import projects_router, work_types_router
from app.server.segments import router as segments_router

app = FastAPI(title="TaskPlanner API", version="0.1.0")
app.include_router(tasks_router)
app.include_router(segments_router)
app.include_router(projects_router)
app.include_router(work_types_router)
app.include_router(capacity_router)
app.include_router(calendar_router)
app.include_router(time_blocks_router)
app.include_router(decomposition_router)
app.include_router(arbitration_router)
app.include_router(protection_router)
app.include_router(planning_router)
app.include_router(morning_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
