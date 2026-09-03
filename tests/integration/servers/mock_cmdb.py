"""Mock CMDB：GET /services/{service} 200 命中契约 / 404 未命中；GET /health 200。"""
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException

DATA = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "cmdb_data.json")
                  .read_text(encoding="utf-8"))

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/services/{service}")
def get_service(service: str) -> dict:
    item = DATA.get(service)
    if item is None:
        raise HTTPException(404, "not found")
    return item


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning")
