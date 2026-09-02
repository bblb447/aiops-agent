from fastapi import APIRouter, HTTPException

from app.workload.model import Workload
from app.workload.service import WorkloadService, WorkloadUnavailable, WorkloadQueryError

router = APIRouter(prefix="/api/v1/workload")


@router.get("/{service}", response_model=Workload)
def get_workload(service: str):
    from app.main import current_settings
    url = current_settings().prometheus_url
    try:
        return WorkloadService(url).get_workload(service)
    except WorkloadUnavailable as e:
        raise HTTPException(503, str(e)) from e
    except WorkloadQueryError as e:
        raise HTTPException(502, str(e)) from e
