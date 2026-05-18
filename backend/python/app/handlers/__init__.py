"""
Redis 큐 작업 핸들러 패키지.

각 job_type 별로 파일 하나. worker.py 의 dispatch_job 이 JOB_HANDLERS 로 분기.
모든 핸들러는 `async def handle(job_id: int, params: dict) -> None` 시그니처 공유.
"""
from app.handlers import brand, detect, export, place, space_data

# dispatch 분기표 — worker.py 의 dispatch_job 이 참조
JOB_HANDLERS = {
    "detect": detect.handle,
    "brand": brand.handle,
    "space_data": space_data.handle,
    "place": place.handle,
    "export": export.handle,
}
