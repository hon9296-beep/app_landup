"""
brand 작업 핸들러 — 브랜드 매뉴얼 LLM 추출.

params:
  - user_id (int, 필수)
  - brand_manual_id (int, 필수)
  - project_id (선택)
  - file_bytes_b64 (str, Base64 PDF)

흐름:
  1. running 알림
  2. nodes_small/reference.py 호출 → brand_data 추출
  3. done 알림 + Java에 결과 전달
"""
import base64
import logging

from app.services.java_callback import notify_java

logger = logging.getLogger(__name__)


async def handle(job_id: int, params: dict) -> None:
    """브랜드 메뉴얼 추출 작업 — Claude LLM 호출."""
    project_id = params.get("project_id")

    await notify_java(job_id, status="running")

    try:
        user_id = params.get("user_id")
        brand_manual_id = params.get("brand_manual_id")
        b64 = params.get("file_bytes_b64", "")
        if not b64:
            raise ValueError("file_bytes_b64 missing")
        brand_bytes = base64.b64decode(b64)

        await notify_java(
            job_id,
            progress={"stage": "reference", "pct": 30, "message": "브랜드 메뉴얼 분석 중"},
        )

        # 라우터 코드와 동일 경로 사용 — 로직 중복 방지
        from app.nodes_small.reference import run as reference_run

        result = reference_run({"brand_bytes": brand_bytes})
        brand_data = result.get("brand_data", {})

        await notify_java(
            job_id,
            status="done",
            user_id=user_id,
            brand_manual_id=brand_manual_id,
            project_id=project_id,
            result=brand_data,
            progress={"stage": "done", "pct": 100, "message": "완료"},
        )
        logger.info(f"[handle_brand] 완료 job_id={job_id}")

    except Exception as e:
        logger.error(f"[handle_brand] 실패 job_id={job_id}: {e}", exc_info=True)
        await notify_java(job_id, status="error", project_id=project_id, error_message=str(e))
