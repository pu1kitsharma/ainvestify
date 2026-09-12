"""
FastAPI app entry point (plan §2). Local-only for this phase -- no auth,
no deployment config, CORS opened for a local Vite dev server only.

Run with: uvicorn api.main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import compilation, dashboard, deals, investors, leads, prompt, research, review

app = FastAPI(title="Deal Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(deals.router)
app.include_router(review.router)
app.include_router(research.router)
app.include_router(investors.router)
app.include_router(leads.router)
app.include_router(prompt.router)
app.include_router(compilation.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
