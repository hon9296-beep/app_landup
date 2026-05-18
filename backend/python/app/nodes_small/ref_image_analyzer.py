"""
레퍼런스 이미지 Vision 분석 노드.

ref_image_loader가 수집한 이미지를 Claude Vision으로 구조화 분석.
'보는' 단계를 독립시켜서, design 노드에는 분석 결과 텍스트만 전달.
이미지 base64는 이 노드에서만 사용하고 design에는 넘기지 않음.

2026-04-20 확장:
- Per-image 분석 추가 (이미지별 내용 판정 + 사용 의도)
- 통합 추적 dump `ref_trace.json` 생성 (loader 메타 + analyzer 출력 병합)
"""
import json
import logging
import os

from anthropic import Anthropic
from pydantic import Field

from app.nodes_small.llm_policy import StrictLLMModel
from app.state import SmallState

logger = logging.getLogger(__name__)


# 2026-04-29: LLM 응답 Pydantic 모델 — call_llm_tool_use 의 response_model 인자.
# Anthropic tool_use schema (VISION_ANALYSIS_TOOL.input_schema) 와 1:1 매핑.
# StrictLLMModel: extra="allow" + 위험 키 거부 + 새 필드 로깅 (app.llm_policy).
class VisionAnalysisResult(StrictLLMModel):
    # #493 — 실사 판별 사전 분기. is_real_photo=False 면 호출자가 결과 폐기.
    is_real_photo: bool = True
    reject_reason: str = "실사"
    # 1-3 (#523) — per-image 카테고리 부합 검증. 명백히 다른 업종 매장 인덱스 list.
    # 예: 뷰티 검색에 TENGA / 바른생각 (성인용품) 섞임 → 해당 인덱스만 reject.
    # 거부된 이미지는 통합 분석에서 제외 + ref_image_loader 의 _rejected_hashes.json 에 등록되어
    # 다음 검색에서도 차단. is_real_photo=False 시 빈 배열 (전체 batch reject 라 per-image 무의미).
    rejected_image_indices: list[int] = Field(default_factory=list)
    rejected_image_reasons: list[str] = Field(default_factory=list)
    layout_patterns: list = Field(default_factory=list)
    partition_usage: list = Field(default_factory=list)
    focal_points: list = Field(default_factory=list)
    flow_description: str = ""
    density_impression: str = ""
    space_mood: str = ""
    composition_principle: str = ""
    design_highlights: list = Field(default_factory=list)

# Vision LLM prompt / Tool schema — #491 prompts 중앙화 (nodes_small/prompts/ref_image_analyzer.py)
from app.nodes_small.prompts.ref_image_analyzer import (
    VISION_ANALYSIS_SYSTEM,
    VISION_ANALYSIS_TOOL,
    VISION_ANALYSIS_PROMPT,
)


def run(state: SmallState) -> SmallState:
    """레퍼런스 이미지 Vision 분석 → ref_analysis 반환.

    Returns: {"ref_analysis": RefAnalysisDict} (state.RefAnalysisDict 참조).
    4 path 모두 동일 형식: 성공 시 layout_patterns/focal_points 등 8 필드, 비정상 시 빈 dict.
    envelope (status/result) 구조 X — 사용처는 state.is_ref_analysis_empty helper 사용.

    reference_meta와 병합해 통합 ref_trace.json 생성. 추적 가능성 확보.
    """
    reference_images = state.get("reference_images") or []
    reference_meta = state.get("reference_meta") or {}

    # 통합 trace dump의 베이스 — 분석 스킵 경로에서도 기록 남김
    trace: dict = {
        "search": reference_meta,
        "analyzer": {
            "status": None,
            "model": None,
            "temperature": None,
            "result": {},
            "skip_reason": None,
        },
    }

    if not reference_images:
        logger.info("[ref_image_analyzer] 레퍼런스 이미지 없음 — 스킵")
        trace["analyzer"]["status"] = "skipped"
        trace["analyzer"]["skip_reason"] = "reference_images 비어있음 (loader 단계에서 이미지 0건)"
        _dump_trace(trace)
        return {"ref_analysis": {}}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[ref_image_analyzer] API 키 없음 — 스킵")
        trace["analyzer"]["status"] = "skipped"
        trace["analyzer"]["skip_reason"] = "ANTHROPIC_API_KEY 환경 변수 없음"
        _dump_trace(trace)
        return {"ref_analysis": {}}

    client = Anthropic(api_key=api_key)

    brand_data = state.get("brand_data") or {}
    category = brand_data.get("brand", {}).get("brand_category", "기타")
    if isinstance(category, dict):
        category = category.get("value", "기타")

    # Vision API 메시지 구성
    analyzed_images = reference_images[:5]
    content: list[dict] = []
    content.append({
        "type": "text",
        "text": (
            f"아래는 '{category}' 카테고리 팝업스토어/전시 공간의 레퍼런스 이미지 {len(analyzed_images)}장입니다.\n"
            f"각 이미지를 주의 깊게 관찰하고, 순서대로(0부터) 배치 설계에 참고할 패턴을 분석해주세요."
        ),
    })
    for img in analyzed_images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["base64"],
            },
        })
    # ⚠ tool use 전환 후 VISION_ANALYSIS_PROMPT는 사용 안 함 (스키마가 강제). 방어선으로 둠.
    # content.append({"type": "text", "text": VISION_ANALYSIS_PROMPT})  # 과거 방식 (파싱 실패 잦음)

    # LLM 설정 중앙 관리 (app.llm_config)
    # 키 "small.ref_image_analyzer" = 네임스페이스 규약. "small." prefix 제거 금지.
    # 상세: app/llm_config.py 최상단
    from app.llm_config import get_llm_config
    _cfg = get_llm_config("small.ref_image_analyzer")
    trace["analyzer"]["model"] = _cfg["model"]
    trace["analyzer"]["temperature"] = _cfg["temperature"]
    trace["analyzer"]["max_tokens"] = _cfg["max_tokens"]
    trace["analyzer"]["analyzed_image_count"] = len(analyzed_images)
    trace["analyzer"]["mode"] = "tool_use"

    # 2026-04-29: LLM 호출을 app.llm_harness.call_llm_tool_use 로 위임.
    # 기존 try/except + tool_use block 추출 + token_tracker 수동 호출 → 하네스가 일괄 처리.
    # 응답 schema (Pydantic VisionAnalysisResult) 는 모듈 상단 정의.
    from app.nodes_small.llm_harness import (
        call_llm_tool_use,
        LLMHarnessError, LLMResponseEmptyError, LLMNoToolUseError,
    )

    try:
        result_obj, meta = call_llm_tool_use(
            client,
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=VISION_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": content}],
            tool_name="analyze_reference_images",
            tool_schema=VISION_ANALYSIS_TOOL,
            response_model=VisionAnalysisResult,
            track_usage_node="ref_image_analyzer",
            max_attempts=3,
        )
        # Pydantic → dict 변환 (기존 코드 호환). exclude_none=False 로 빈 필드 보존.
        result = result_obj.model_dump()

        # #493 — 실사 판별. is_real_photo=False 면 design 학습 못 하도록 결과 폐기.
        if not result.get("is_real_photo", True):
            reject_reason = result.get("reject_reason", "비실사")
            logger.warning(
                "[ref_image_analyzer] 비실사 이미지 — 분석 결과 폐기 (reject_reason=%s, attempts=%d)",
                reject_reason, meta.get("attempts", 1),
            )
            # Java blacklist 자동 등록 — 다음 DDG 다운로드 / 캐시 hit 모두 차단.
            # 통합 reject 라 batch 의 모든 이미지 sha256 등록 (per-image 분기는 후속 PR).
            try:
                from app.clients.ref_image_client import mark_blacklisted as _mark_bl
                blacklist_marked: list[dict] = []
                for img_meta in (reference_meta.get("images_meta") or []):
                    sha = img_meta.get("hash_full")
                    if not sha:
                        continue
                    marked = _mark_bl(sha, reason=reject_reason)
                    blacklist_marked.append({"sha256_prefix": sha[:12], "marked": marked})
                trace["analyzer"]["blacklist_marked"] = blacklist_marked
                logger.info(
                    "[ref_image_analyzer] blacklist 자동 등록: %d 건 시도",
                    len(blacklist_marked),
                )
            except Exception as _bl_e:
                logger.warning(f"[ref_image_analyzer] blacklist 등록 실패 (graceful): {_bl_e}")

            trace["analyzer"]["status"] = "rejected_render"
            trace["analyzer"]["reject_reason"] = reject_reason
            trace["analyzer"]["result"] = result  # 원본 보존 (디버깅용)
            trace["analyzer"]["token_usage"] = {
                "input_tokens": meta.get("input_tokens"),
                "output_tokens": meta.get("output_tokens"),
            }
            trace["analyzer"]["attempts"] = meta.get("attempts", 1)
            _dump_trace(trace)
            return {"ref_analysis": {}}

        # 1-3 (#523) — per-image 카테고리 mismatch 처리.
        # rejected_image_indices 박힌 이미지만 blacklist + local _rejected_hashes 등록.
        # 정상 이미지의 통합 분석 결과는 보존 (over-reject 방지).
        rejected_indices = result.get("rejected_image_indices") or []
        rejected_reasons_list = result.get("rejected_image_reasons") or []
        if rejected_indices:
            try:
                from app.clients.ref_image_client import mark_blacklisted as _mark_bl
                imgs_meta = (reference_meta.get("images_meta") or [])
                category_blacklist_marked: list[dict] = []
                local_rejected_hashes: list[tuple[str, str]] = []  # (sha256_full, category_slug)
                category_slug = (reference_meta.get("handoff") or {}).get("category_slug") or "other"
                for pos, idx in enumerate(rejected_indices):
                    if not isinstance(idx, int) or idx < 0 or idx >= len(imgs_meta):
                        continue
                    img_meta = imgs_meta[idx]
                    sha = img_meta.get("hash_full")
                    if not sha:
                        continue
                    reason = (
                        rejected_reasons_list[pos]
                        if pos < len(rejected_reasons_list)
                        else "카테고리 불일치"
                    )
                    # Java blacklist 등록 (graceful — Java 다운 시 None 반환)
                    marked = _mark_bl(sha, reason=f"카테고리 불일치: {reason}")
                    category_blacklist_marked.append({
                        "image_index": idx,
                        "sha256_prefix": sha[:12],
                        "marked": marked,
                        "reason": reason[:200],
                    })
                    local_rejected_hashes.append((sha, category_slug))
                trace["analyzer"]["category_mismatch_rejected"] = category_blacklist_marked
                # local _rejected_hashes.json 등록 (Java handoff 안 가도 다음 검색 차단)
                _write_local_rejected_hashes(local_rejected_hashes)
                logger.warning(
                    "[ref_image_analyzer] 카테고리 mismatch 거부 %d 건: %s",
                    len(category_blacklist_marked),
                    [m["reason"][:60] for m in category_blacklist_marked],
                )
            except Exception as _bl_e:
                logger.warning(f"[ref_image_analyzer] category mismatch blacklist 등록 실패 (graceful): {_bl_e}")

        logger.info(
            "[ref_image_analyzer] 분석 완료: patterns=%d, partitions=%d, focal=%d, rejected=%d (attempts=%d)",
            len(result.get("layout_patterns", [])),
            len(result.get("partition_usage", [])),
            len(result.get("focal_points", [])),
            len(rejected_indices),
            meta.get("attempts", 1),
        )

        trace["analyzer"]["status"] = "ok"
        trace["analyzer"]["result"] = result
        trace["analyzer"]["rejected_image_count"] = len(rejected_indices)
        trace["analyzer"]["token_usage"] = {
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
        }
        trace["analyzer"]["attempts"] = meta.get("attempts", 1)

        # 디버그 덤프 — 기존 ref_analysis.json은 backward-compat으로 유지
        from datetime import datetime
        debug_dir = os.path.join(os.path.dirname(__file__), "..", "..", "debug_logs", datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, "ref_analysis.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info("[ref_image_analyzer] 덤프 저장: ref_analysis.json")

        _dump_trace(trace)
        return {"ref_analysis": result}

    except LLMResponseEmptyError as e:
        logger.warning(f"[ref_image_analyzer] 빈 응답 (재시도 소진): {e}")
        trace["analyzer"]["status"] = "empty_response"
        trace["analyzer"]["error"] = str(e)[:500]
        _dump_trace(trace)
        return {"ref_analysis": {}}
    except LLMNoToolUseError as e:
        logger.warning(f"[ref_image_analyzer] tool_use 미반환 (재시도 소진): {e}")
        trace["analyzer"]["status"] = "no_tool_block"
        trace["analyzer"]["error"] = str(e)[:500]
        _dump_trace(trace)
        return {"ref_analysis": {}}
    except LLMHarnessError as e:
        logger.warning(f"[ref_image_analyzer] 하네스 실패: {type(e).__name__}: {e}")
        trace["analyzer"]["status"] = "harness_error"
        trace["analyzer"]["error"] = f"{type(e).__name__}: {str(e)[:500]}"
        _dump_trace(trace)
        return {"ref_analysis": {}}
    except Exception as e:
        logger.warning("[ref_image_analyzer] Vision 분석 실패 (무시): %s", e)
        trace["analyzer"]["status"] = "error"
        trace["analyzer"]["error"] = str(e)[:500]
        _dump_trace(trace)
        return {"ref_analysis": {}}


def _write_local_rejected_hashes(hashes_with_slug: list) -> None:
    """1-3 (#523) — 카테고리 mismatch 로 거부된 이미지 hash 를 카테고리 폴더의 _rejected_hashes.json 에 append.

    ref_image_loader 가 다음 다운로드 전 이 list 체크 → 같은 hash 차단 (Java handoff 미가동 환경 대비
    local fallback). _hashes.json (정상 캐시) 와는 별도 파일로 분리해 dedup 룰 안 깨짐.

    Args:
        hashes_with_slug: [(sha256_full, category_slug), ...]
    """
    if not hashes_with_slug:
        return
    try:
        import json as _json
        from app.nodes_small.ref_image_loader import IMAGES_DIR
        # category_slug 별로 묶어서 처리
        by_slug: dict[str, list[str]] = {}
        for sha, slug in hashes_with_slug:
            by_slug.setdefault(slug, []).append(sha)
        for slug, shas in by_slug.items():
            folder = IMAGES_DIR / slug
            folder.mkdir(parents=True, exist_ok=True)
            rejected_file = folder / "_rejected_hashes.json"
            existing: list = []
            if rejected_file.exists():
                try:
                    existing = _json.loads(rejected_file.read_text(encoding="utf-8"))
                except Exception:
                    existing = []
            merged = sorted(set(existing) | set(shas))
            rejected_file.write_text(_json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(
                "[ref_image_analyzer] _rejected_hashes.json 갱신: %s (+%d, total=%d)",
                slug, len(shas), len(merged),
            )
    except Exception as _e:
        logger.warning(f"[ref_image_analyzer] _rejected_hashes.json 갱신 실패 (graceful): {_e}")


def _dump_trace(trace: dict) -> None:
    """loader 메타 + analyzer 결과 통합 trace를 ref_trace.json + timestamp 버전 저장.

    2026-04-20: 과거엔 무버전 하나만 덮어쓰기 → 초기 DDG 검색 rationale 유실.
    다른 debug 파일(place_result, design_intents)과 동일하게 timestamp 버전 병행 저장.
    """
    try:
        from datetime import datetime
        now = datetime.now()
        debug_dir = os.path.join(os.path.dirname(__file__), "..", "..", "debug_logs", now.strftime("%Y-%m-%d"))
        os.makedirs(debug_dir, exist_ok=True)
        # JSON 직렬화 불가 객체(Path 등) 보정
        safe_trace = _jsonify(trace)
        # 무버전 (최신) + timestamp 버전 둘 다 저장
        ts = now.strftime("%Y-%m-%d_%H-%M-%S")
        for fname in ("ref_trace.json", f"{ts}_ref_trace.json"):
            with open(os.path.join(debug_dir, fname), "w", encoding="utf-8") as f:
                json.dump(safe_trace, f, ensure_ascii=False, indent=2)
        logger.info("[ref_image_analyzer] 통합 trace 덤프: ref_trace.json + %s_ref_trace.json", ts)
    except Exception as e:
        logger.warning("[ref_image_analyzer] ref_trace.json 덤프 실패: %s", e)


def _jsonify(obj):
    """직렬화 불가 객체(Path, set 등)를 str/list로 변환."""
    from pathlib import Path
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_jsonify(v) for v in obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj
