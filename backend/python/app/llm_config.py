"""
LLM 호출 설정 중앙 관리 — 전 파이프라인 공유.

모든 LLM 호출이 이 파일의 `LLM_CONFIG`에서 model / temperature / max_tokens을 조회한다.
노드 코드는 `get_llm_config(node_name)`만 호출하고 실제 값은 여기서만 수정.

═══════════════════════════════════════════════════════════════════════════
[중요/회귀방지] 키 네이밍 규약 — 2026-04-20 확정
═══════════════════════════════════════════════════════════════════════════

키는 다음 네임스페이스로 구분한다:

  1. "small.<node_name>"  — 소·중형 파이프라인(nodes_small/) 전용
                             예: "small.reference", "small.design",
                                 "small.ref_image_analyzer"
  2. "large.<node_name>"  — 대형·야외 파이프라인(nodes_large/, Shin 영역) 전용
                             (현재 미등록. Shin이 이 패턴 채택 시 추가)
  3. "<shared_name>"      — prefix 없음 = 파이프라인 공유 모듈
                             예: "intent_parser" (core/intent_parser.py는
                                  large/small 양쪽에서 호출 가능)

▲▲▲ 이 prefix 규약을 절대 임의로 제거하거나 바꾸지 말 것 ▲▲▲

- small 키의 "small." prefix를 지우면 향후 Shin이 "large.reference"를 추가하려
  할 때 키 충돌("reference" vs "small.reference")로 혼란 발생.
- "파일 경로는 global인데 왜 키만 small이냐?" 라는 의문이 들 수 있으나
  이는 의도된 것. `core/intent_parser.py`가 core 계층에 있어 `nodes_small/`
  하위로 파일 이동 시 **core → nodes_small 역방향 import(계층 침범)**가
  발생하므로 파일은 top-level(`app/llm_config.py`) 유지. 대신 키 네임스페이스
  로 스코프 명시.
- 기존 flat 키("reference", "design" 등 prefix 없음)로 되돌리면 바로 위 혼란
  재발. 이전 구조와 회귀 이력은 아래 참고 문서에 명시.

═══════════════════════════════════════════════════════════════════════════

## 정책 (temperature 기준)

- **파싱·해석** (small.reference, intent_parser): temperature=0
  → 같은 입력은 같은 출력 강제. 결정론 필수.
- **창의 설계** (small.design): temperature=0.3
  → 약간의 다양성 허용하되 과도한 variance 억제.
- **시각 분석** (small.ref_image_analyzer): temperature=0.3
  → 이전부터 설정된 값 유지.

## 배경 (2026-04-20 Tier 1-0)

이전까지 대부분 노드가 `temperature` 인자를 생략하여 Anthropic SDK 기본값(1.0)으로
동작. 같은 brand PDF를 재업로드해도 파싱 결과가 매번 달라지는 비결정성 문제 발생
(debug_logs의 brand_data hash 4회 모두 상이 확인됨). 본 파일로 중앙화하면서 파싱/
해석 단계는 0, 설계 단계는 0.3으로 고정.

## 모델 관리

- `small.ref_image_analyzer`의 모델은 2026-04-20 기준 outdated
  (`claude-sonnet-4-5-20250514`). Tier 1-4에서 `claude-sonnet-4-6` 등으로 교체
  예정. 본 파일 한 줄만 수정하면 됨.

## 참고 문서

- reports/AD/2026-04-20_small_store_finalization_tier1.md (Tier 1-0)
- reports/AD/2026-04-20_small_pipeline_db_schema.md (DB 설계용 설명)
"""
from __future__ import annotations


# ── LLM 호출별 설정 ───────────────────────────────────────────────────────

LLM_CONFIG: dict[str, dict] = {
    # ═══════════════════════════════════════════════════════════════════
    # 소·중형 파이프라인 (nodes_small/ 전용)
    # ═══════════════════════════════════════════════════════════════════

    # 브랜드 매뉴얼 PDF → placement_rules 추출 (nodes_small/reference.py)
    # 같은 PDF = 같은 rule 강제 (temperature=0 필수)
    "small.reference": {
        "model": "claude-sonnet-4-6",
        "temperature": 0,
        "max_tokens": 3072,
    },

    # 공간 + eligible + intent → design_intents (nodes_small/design.py)
    # 일부 다양성 허용 (temperature=0.3)
    "small.design": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.3,
        "max_tokens": 8192,
    },

    # 레퍼런스 이미지 Vision 분석 → ref_analysis (nodes_small/ref_image_analyzer.py)
    # 2026-04-20 Tier 1-4: claude-sonnet-4-5-20250514 (outdated) → 4-6 교체
    # 2026-04-20 tool_use 전환 + 스키마 간소화로 2048 유지. 이전 4096 확대 시도는 token 낭비로 되돌림.
    "small.ref_image_analyzer": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.3,
        "max_tokens": 2048,
    },

    # design_intents anti-pattern 검토 (nodes_small/design_reviewer.py, #474 도박수)
    # 검토 = 판정 → 약한 결정론 (temperature=0.2)
    "small.design_reviewer": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.2,
        "max_tokens": 2048,
    },

    # 도면 이미지 vision 파싱 — 입구/설비 좌표 추출 (nodes_small/vision.py)
    # 객관적 사실 추출 (좌표/위치) → 결정론 필수 (temperature=0)
    "small.vision": {
        "model": "claude-sonnet-4-6",
        "temperature": 0,
        "max_tokens": 1024,
    },

    # 도면 이미지 vision 파싱 — floor_polygon_px 추출 (nodes_small/parser_image.py)
    # 2026-05-04 #491: 이전까지 temperature 인자 누락 → SDK 기본값 1.0 사용 중이었음.
    # 정책 적용 — 파싱은 결정론 필수 (temperature=0).
    "small.parser_image": {
        "model": "claude-sonnet-4-6",
        "temperature": 0,
        "max_tokens": 2048,
    },

    # 컨셉 자연어 생성 (nodes_small/concept_gen.py, placeholder 노드)
    # 창의적 다양성 의도 (temperature=0.7 보존 — 향후 정책 재검토 대상)
    "small.concept_gen": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.7,
        "max_tokens": 1024,
    },

    # ═══════════════════════════════════════════════════════════════════
    # 대형·야외 파이프라인 (nodes_large/ 전용, Shin 영역)
    # ═══════════════════════════════════════════════════════════════════
    # 2026-04-24 TR R 착수 — large 키 등록 시작.
    # 추후 large.reference / large.design / large.placement 등 추가 예정.

    # 레퍼런스 이미지 Vision 분석 → ref_analysis (nodes_large/ref_image_analyzer.py)
    # 2026-04-24 TR R: Haiku 하드코딩 → Sonnet 4-6 으로 교체 (small 과 동일 모델).
    # max_tokens 2048 유지 (per_image_analysis 미도입 결정, Phase 2 에서 4096 재검토).
    "large.ref_image_analyzer": {
        "model": "claude-sonnet-4-6",
        "temperature": 0.3,
        "max_tokens": 2048,
    },

    # ═══════════════════════════════════════════════════════════════════
    # 공유 모듈 (small + large 모두 호출 가능)
    # ═══════════════════════════════════════════════════════════════════

    # 사용자 자연어 요구사항 → resolved_intents 구조화 (core/intent_parser.py)
    # 같은 문장 = 같은 intent 강제 (temperature=0 필수)
    # prefix 없음 = 공유 모듈이라는 명시적 표시
    "intent_parser": {
        "model": "claude-haiku-4-5-20251001",
        "temperature": 0,
        "max_tokens": 512,
    },
}


def get_llm_config(node_name: str) -> dict:
    """노드별 LLM 설정 조회.

    Args:
        node_name: 네임스페이스 포함 키.
                   - "small.reference" | "small.design" | "small.ref_image_analyzer"
                   - "intent_parser" (공유)
                   - 향후 "large.*" (Shin 추가 시)

    Returns:
        {"model": str, "temperature": float, "max_tokens": int} dict (복사본)

    Raises:
        KeyError: 등록되지 않은 node_name
    """
    if node_name not in LLM_CONFIG:
        raise KeyError(
            f"[llm_config] unknown node_name: '{node_name}'. "
            f"사용 가능: {list(LLM_CONFIG.keys())}. "
            f"키 네이밍 규약: 'small.*' | 'large.*' | 공유 모듈은 prefix 없음."
        )
    return dict(LLM_CONFIG[node_name])  # caller mutation 방지
