from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.query_routes import router as query_router
from app.api.routes import router as ingestion_router
from app.api.storage_routes import router as storage_router
from app.api.ws_routes import router as ws_router
from app.config import settings

app = FastAPI(title="Weather API")

# Lets a browser-based client (e.g. the admin React app) call this API
# from a different origin. Only affects REST endpoints - WebSocket
# connections aren't subject to CORS preflight the way fetch/XHR are,
# so this doesn't change anything about /ws/* auth behavior.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingestion_router)
app.include_router(query_router)
app.include_router(storage_router)
app.include_router(ws_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
