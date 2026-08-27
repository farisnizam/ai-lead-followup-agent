from fastapi import FastAPI

from app.routers import leads

app = FastAPI(title="AI Lead Follow-up Agent")

app.include_router(leads.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
