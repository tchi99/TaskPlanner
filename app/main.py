from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.security import JwtVerifier, AuthenticationFailure, AuthorizationFailure
from app.server.capacity import router as capacity_router
from app.server.recurring_availability import router as recurring_availability_router
from app.server.weekly_schedule import router as weekly_schedule_router
from app.server.schedule_scopes import router as schedule_scopes_router
from app.server.effective_availability import router as effective_availability_router
from app.server.weekly_eligibility import router as weekly_eligibility_router
from app.server.calendar import router as calendar_router
from app.server.time_blocks import router as time_blocks_router
from app.server.booking_resolutions import router as booking_resolutions_router
from app.server.decomposition import router as decomposition_router
from app.server.arbitration import router as arbitration_router
from app.server.protection import router as protection_router
from app.server.planning import router as planning_router
from app.server.morning import router as morning_router
from app.server.daily import router as daily_router
from app.server.weekly import router as weekly_router
from app.server.start import router as start_router
from app.server.work_sessions import task_router as work_session_task_router, session_router as work_session_router
from app.server.behavior import router as behavior_router

from app.server.tasks import router as tasks_router
from app.server.projects import projects_router, work_types_router
from app.server.segments import router as segments_router

# Fail closed during process initialization before accepting traffic.
settings = get_settings()
settings.validate_security()
app = FastAPI(title="TaskPlanner API", version="0.1.0")
app.state.security_settings = settings
app.state.jwt_verifier = JwtVerifier(settings) if settings.auth_mode == "supabase" else None


@app.middleware("http")
async def enforce_authentication(request: Request, call_next):
    if request.url.path == "/api/health":
        return await call_next(request)
    # Real CORS preflights are checked by the outer CORSMiddleware.
    if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
        return await call_next(request)
    security = request.app.state.security_settings
    if security.auth_mode == "local":
        return await call_next(request)
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token or token.strip() != token or " " in token:
        return JSONResponse(status_code=401, content={"detail": "Authentification requise."},
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        subject = request.app.state.jwt_verifier.verify(token)
    except AuthenticationFailure:
        return JSONResponse(status_code=401, content={"detail": "Jeton invalide ou expiré."},
                            headers={"WWW-Authenticate": "Bearer"})
    except AuthorizationFailure:
        return JSONResponse(status_code=403, content={"detail": "Accès non autorisé."})
    request.state.user_id = subject
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(tasks_router)
app.include_router(segments_router)
app.include_router(projects_router)
app.include_router(work_types_router)
app.include_router(capacity_router)
app.include_router(recurring_availability_router)
app.include_router(weekly_schedule_router)
app.include_router(schedule_scopes_router)
app.include_router(effective_availability_router)
app.include_router(weekly_eligibility_router)
app.include_router(calendar_router)
app.include_router(time_blocks_router)
app.include_router(booking_resolutions_router)
app.include_router(decomposition_router)
app.include_router(arbitration_router)
app.include_router(protection_router)
app.include_router(planning_router)
app.include_router(morning_router)
app.include_router(daily_router)
app.include_router(weekly_router)
app.include_router(start_router)
app.include_router(work_session_task_router)
app.include_router(work_session_router)
app.include_router(behavior_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
