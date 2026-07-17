from fastapi import FastAPI

from app.api.query_routes import router as query_router
from app.api.routes import router as ingestion_router
from app.api.storage_routes import router as storage_router

app = FastAPI(title="Weather API")
app.include_router(ingestion_router)
app.include_router(query_router)
app.include_router(storage_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
