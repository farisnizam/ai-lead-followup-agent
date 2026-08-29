from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import leads, pages

app = FastAPI(title="AI Lead Follow-up Agent")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(leads.router)
app.include_router(pages.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
