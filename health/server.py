from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="health-service", docs_url=None, redoc_url=None)


@app.get("/health")
async def health():
    return JSONResponse(
        status_code=200,
        content={"status": "ok"}
    )


@app.get("/ready")
async def readiness():
    # extend later (db, redis, external APIs)
    return JSONResponse(
        status_code=200,
        content={"status": "ready"}
    )
