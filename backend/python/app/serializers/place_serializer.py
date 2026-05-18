"""
배치 결과 직렬화 — state → JSON 응답.

Java 정본 네이밍 기준 (PlacementResultService.applyPlaceResult 와 계약).
"""
import logging

from app.serializers.space_serializer import _to_concept_area_en, serialize_linestring
from app.services.failure_service import collect_requirement_failures

logger = logging.getLogger(__name__)


def _build_insight_text_map(ref_analysis: dict) -> dict[str, str]:
    """ref_analysis 의 layout_patterns/partition_usage/focal_points/design_highlights 의
    {id: text} lookup 생성. PR #226 Phase 2.1 복원.
    """
    out: dict[str, str] = {}
    for key in ("layout_patterns", "partition_usage", "focal_points", "design_highlights"):
        for item in ref_analysis.get(key) or []:
            if isinstance(item, dict):
                iid = item.get("id")
                txt = item.get("text", "")
                if isinstance(iid, str) and iid:
                    out[iid] = txt
    return out


def format_place_response(state: dict) -> dict:
    """배치 결과 JSON 응답 포맷 — Java 정본 네이밍 기준.

    PlacementResultService.applyPlaceResult 가 읽는 키/구조와 일치.
    scalar (placement_results row) + 하위 리스트 (objects/verifications/failed_objects/cap_logs/token_usage).
    """
    placed = state.get("placed_objects", [])
    failed = state.get("failed_objects", [])
    logger.info(f"[place] 최종: placed={len(placed)}, failed={len(failed)}")

    # PR #226 Phase 2.1 복원: 인사이트 ID → 원문 텍스트 lookup
    insight_text_map = _build_insight_text_map(state.get("ref_analysis") or {})

    requirement_failures = collect_requirement_failures(state)

    # ── cap_log (소형 object_selection) → Java cap_logs 형식 ──
    cap_log_dict = state.get("cap_log") or {}
    cap_logs_list = [
        {"object_type": obj_type, **entry}
        for obj_type, entry in cap_log_dict.items()
    ]

    # ── token_usage_summary → Java TokenUsage 형식 ──
    tus = state.get("token_usage_summary") or {}
    by_node = tus.get("by_node") or {}
    calls = tus.get("calls") or []
    node_model: dict = {}
    for c in calls:
        node_model.setdefault(c.get("node", ""), c.get("model", "unknown"))
    token_usage_list = [
        {
            "node_name": node,
            "input_tokens": v.get("input", 0),
            "output_tokens": v.get("output", 0),
            "cache_read_tokens": v.get("cache_read", 0),
            "cache_write_tokens": v.get("cache_creation", 0),
            "model": node_model.get(node, "unknown"),
        }
        for node, v in by_node.items()
    ]

    # ── verification dict → verifications list 평탄화 (blocking + warning concat) ──
    verification = state.get("verification") or {}
    verifications_list = (
        list(verification.get("blocking") or [])
        + list(verification.get("warning") or [])
    )

    # ── objects (placement_objects 정본 필드명) ──
    # falsy-safe: 빈 문자열도 None 으로 변환 (Java ENUM 컬럼 호환용 — "" 은 유효값 아님)
    def _enum_or_null(v):
        return v if v is not None and v != "" else None
    objects_list = [{
        "object_type": p["object_type"],
        # #472 b-3: 매뉴얼 raw 명명 frontend 도달 (LayoutObject.label fallback object_type)
        "label": p.get("label") or p.get("object_type", ""),
        "anchor_key": p.get("anchor_key", ""),
        "center_x_mm": round(p["center_x_mm"]),
        "center_y_mm": round(p["center_y_mm"]),
        "rotation_deg": p["rotation_deg"],
        "width_mm": p["width_mm"],
        "depth_mm": p["depth_mm"],
        "height_mm": p.get("height_mm", 1500),
        "zone_label": _enum_or_null(p.get("zone_label")),
        "concept_area_id": p.get("concept_area_id"),  # 2026-05-01 Phase 2 — concept_areas FK
        "concept_area": _to_concept_area_en(p.get("concept_area")),  # 2026-05-01 Phase 4 — 응답 시점 영문 변환
        "direction": _enum_or_null(p.get("direction")),
        "alignment": _enum_or_null(p.get("alignment")),
        "wall_attachment": _enum_or_null(p.get("wall_attachment")),
        "category": p.get("category"),
        "placed_because": p.get("placed_because", ""),
        # PR #226 Phase 2 복원: ref 이미지 추적 — 프론트 3D 뷰어 호버 카드용
        "inspired_by_images": p.get("inspired_by_images") or [],
        # PR #226 Phase 2.1 복원: 인사이트 ID + resolved 텍스트
        "inspired_by_insights": [
            {"id": iid, "text": insight_text_map.get(iid, "")}
            for iid in (p.get("inspired_by_insights") or [])
        ],
        # 2026-04-29 (#114 + #115): partition_wall 의 graphic_face 메타.
        # partition 외 객체는 "none" 기본. partition 만 entry 에서 실제 값 보유.
        "graphic_face": p.get("graphic_face", "none"),
        "graphic_face_basis": p.get("graphic_face_basis", "default_front"),
    } for p in placed]

    # ── failed_objects (정본) ──
    failed_objects_list = [
        {"object_type": f.get("object_type", "unknown"), "reason": f.get("reason", "unknown")}
        for f in failed
    ]

    # ── concept_areas (2026-05-01 Phase 4-2 갈래 3 — 사이클 후 spaceData 갱신용) ──
    # 사이클 직후 ResultPage 의 spaceData 는 도면 분석 시점 응답이라 concept_areas 비어있음.
    # 사이클 응답에 같이 담아서 프론트가 setSpaceData(merge) 로 갱신하게 함.
    # 응답: [{"name": "welcome"(EN), "polygon_mm": [[x,y],...], "area_ratio": float}, ...]
    concept_areas_list = []
    for area in state.get("concept_areas", []) or []:
        poly = area.get("polygon_mm")
        if poly is None or not hasattr(poly, "exterior"):
            continue
        coords = [[round(c[0], 1), round(c[1], 1)] for c in poly.exterior.coords[:-1]]
        name_ko = area.get("name") or ""
        concept_areas_list.append({
            "name": _to_concept_area_en(name_ko),
            "polygon_mm": coords,
            "area_ratio": round(area.get("area_ratio", 0.0), 4),
        })

    response = {
        # placement_results scalar 필드 (Java applyPlaceResult 가 읽음)
        "placed_count": len(objects_list),
        "failed_count": len(failed_objects_list),
        "fallback_round": state.get("fallback_round", 0),
        "verification_passed": bool(verification.get("passed", False)),
        "ref_quality_score": state.get("ref_quality_score"),
        "density_ratio": state.get("density_ratio"),
        "user_requirements": state.get("user_requirements"),
        "report_text": state.get("report_text", ""),
        "report_json": state.get("report_json", {}),
        "glb_path": state.get("glb_path"),

        # 하위 리스트 (Java 가 전담 Service 에 위임)
        "objects": objects_list,
        "failed_objects": failed_objects_list,
        "verifications": verifications_list,
        "cap_logs": cap_logs_list,
        "token_usage": token_usage_list,

        # 프론트/디버그 보조 (Java DB 미저장)
        "concept_areas": concept_areas_list,  # 2026-05-01 Phase 4-2 갈래 3 — spaceData 갱신용
        "requirement_failures": requirement_failures,
        "pathways": state.get("pathways", []),
        "trapped_objects": state.get("trapped_objects", []),
        "ref_point_status": state.get("ref_point_status", []),
        "intent_parse_error": state.get("intent_parse_error"),  # LLM 실패 시 사유 (프론트 알림용)
        # 2026-04-29 (#264 fail-loud): design fallback 발생 시 사유 응답에 노출.
        # None = LLM 정상 호출 / "REF_CONTEXT_MISSING" / "API_KEY_MISSING" / "CIRCUIT_BREAKER: ..."
        # 프론트가 이 필드 보고 사용자에게 경고 표시 (배치 품질 저하 인지).
        "design_fallback_reason": state.get("design_fallback_reason"),
        # 2026-04-29 (#116 F-8 복원) → 2026-05-04 형식 변경.
        # 변경 전: 단일 라인 [[x_mm, y_mm], ...]
        # 변경 후: 여러 라인 [[[x_mm, y_mm], [x_mm, y_mm]], ...] (각 가지 = 별 라인)
        # main_artery 의 가지 동선들 (sub_path 노드 결과). 빈 list 가능.
        # 프론트 Viewer3D 가 받아서 가지 별 라인 그림.
        "sub_path": state.get("sub_path", []),
        # 2026-05-04 신설 — main_artery 가 b_space_data 에서 place 단계로 이동 (배치 후 동선 계산).
        # space 응답 (space_serializer) 에는 더 이상 main_artery 안 박힘.
        # place 응답에 박아서 프론트가 동선 시각화 가능.
        # [[x_mm, y_mm], ...] 좌표 list. 순환 동선 (loop spine) 또는 일자 fallback.
        "main_artery": serialize_linestring(state.get("main_artery")),
    }

    return response


def serialize_result(result: dict) -> dict:
    """LangGraph 파이프라인 결과 → JSON 직렬화 (정본 네이밍). /api/run 디버그용."""
    from app.utils import serialize_placement
    placed = result.get("placed_objects", [])
    failed = result.get("failed_objects", [])
    verification = result.get("verification") or {}
    verifications_list = (
        list(verification.get("blocking") or [])
        + list(verification.get("warning") or [])
    )
    return {
        "objects": [serialize_placement(p) for p in placed],
        "failed_objects": failed,
        "verifications": verifications_list,
        "verification_passed": bool(verification.get("passed", False)),
        "report_text": result.get("report_text", ""),
    }
