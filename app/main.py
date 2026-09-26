from fastapi import FastAPI

from app.server.tasks import router as tasks_router

app = FastAPI(title="TaskPlanner API", version="0.1.0")
app.include_router(tasks_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
