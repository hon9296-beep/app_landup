"""/api/report/latest — 최근 배치 사이클 분석 리포트.

FE 컴포넌트 (components/mypage/AnalysisReport.tsx) 의 AnalysisReportData 타입과
1:1 매칭되는 JSON 응답. TypeScript 타입이 API contract 역할.
응답 스키마 변경 시 FE 타입도 같이 갱신해야 함.
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.report_service import _build_report_data, build_report_from_frontend

router = APIRouter()
logger = logging.getLogger(__name__)


class ReportGenerateRequest(BaseModel):
    placed_objects: list[Any] = []
    failed_objects: list[Any] = []
    dead_zones: list[Any] = []
    token_usage: list[Any] = []
    pair_rules: list[Any] = []
    brand_data: dict[str, Any] = {}
    area_m2: float | None = None
    ceiling_height_mm: float | None = None
    entrance_count: int = 0
    sprinkler_count: int = 0
    brand_category: str = "기타"
    ref_quality_score: float | None = None


@router.get("/api/report/latest")
def api_report_latest():
    """최근 배치 사이클의 분석 리포트 데이터.

    debug_logs/YYYY-MM-DD/ 의 최신본 JSON 파일들을 읽어 FE AnalysisReportData
    스키마로 조립하여 반환. 세션/프로젝트 분리는 미구현 — 현재는 전역 "마지막 사이클"만.
    """
    try:
        data = _build_report_data()
        if data is None:
            raise HTTPException(status_code=404, detail="최근 배치 사이클 데이터 없음. 먼저 배치를 실행하세요.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[report] /api/report/latest 실패")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/report/generate")
def api_report_generate(body: ReportGenerateRequest):
    """프론트 보유 데이터로 리포트 즉시 생성.

    기존 프로젝트처럼 DB 에 report_json 이 없을 때 fallback 용도.
    """
    try:
        return build_report_from_frontend(body.model_dump())
    except Exception as e:
        logger.exception("[report] /api/report/generate 실패")
        raise HTTPException(status_code=500, detail=str(e))
