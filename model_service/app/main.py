from fastapi import FastAPI

app = FastAPI(title="Drift Triage — Model Service")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
