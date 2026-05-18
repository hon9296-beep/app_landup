"""
시스템 핵심 예외 클래스 — Rendy RendyBaseError 계층 이식.

예외 타입별 retry 분기에 사용.
failure_handler(fallback) 재호출 시 _RETRYABLE_EXCEPTIONS로 retry 여부 판단.
"""


class LandupBaseError(Exception):
    """프로젝트 최상위 예외."""
    def __init__(self, message: str, context: dict | None = None):
        super().__init__(message)
        self.context = context or {}


# ── LLM 관련 ────────────────────────────────────────────────────────────────

class LLMTimeoutError(LandupBaseError):
    """Claude API 호출 타임아웃."""
    pass


class LLMParsingError(LandupBaseError):
    """LLM 응답 JSON 파싱 실패."""
    pass


class LLMValidationError(LandupBaseError):
    """LLM 출력이 검증 실패 (Circuit Breaker 트리거)."""
    pass


# ── 기하학 연산 ──────────────────────────────────────────────────────────────

class GeometryCalculationError(LandupBaseError):
    """Shapely/NetworkX 기하학 연산 실패."""
    pass


class PolygonDegenerateError(GeometryCalculationError):
    """polygon이 퇴화 (면적 0, 자기 교차 등)."""
    pass


# ── 파서 ─────────────────────────────────────────────────────────────────────

class ParserError(LandupBaseError):
    """도면 파싱 실패."""
    pass


class VisionAPIError(ParserError):
    """Claude Vision API 호출 실패."""
    pass


class ScaleEstimationError(ParserError):
    """스케일 산출 실패 (치수선 없음 등)."""
    pass


# ── 배치 엔진 ────────────────────────────────────────────────────────────────

class PlacementError(LandupBaseError):
    """배치 엔진 실행 중 오류."""
    pass


class AllSlotsExhaustedError(PlacementError):
    """모든 slot에서 배치 실패."""
    pass


class CircuitBreakerTrippedError(PlacementError):
    """Agent 3 Circuit Breaker 3회 초과."""
    pass


# ── 외부 서비스 ──────────────────────────────────────────────────────────────

class ExternalServiceError(LandupBaseError):
    """외부 서비스 연결 실패."""
    pass


# ── retry 분기용 ─────────────────────────────────────────────────────────────

RETRYABLE_EXCEPTIONS = (AllSlotsExhaustedError, LLMValidationError, LLMParsingError)
