"""
export 작업 핸들러 — GLB / 보고서 내보내기 (placeholder).

B-5 이후 구현 예정. dispatch 시 NotImplementedError 를 raise 하면
worker.dispatch_job 이 Java 에 "핸들러 미구현" 에러 콜백.
"""


async def handle(job_id: int, params: dict) -> None:
    """GLB/보고서 내보내기 핸들러. 향후 구현 예정."""
    raise NotImplementedError("향후 구현 예정")
