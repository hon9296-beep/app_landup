"""debug_logs → AnalysisReportData 조립 서비스.

FE 컴포넌트 (components/mypage/AnalysisReport.tsx) 의 AnalysisReportData 타입과
1:1 매칭되는 dict 를 조립. 응답 스키마 변경 시 FE 타입도 같이 갱신해야 함.
"""
import json
import logging
import os
import re
from collections import Counter

logger = logging.getLogger(__name__)


# 사용자 언어로 표시할 매핑 — FE 에서도 동일 치환 (중복 최소화 위해 BE 에서 선처리)
_RELATION_KEEP = {"adjacent", "join", "separate"}  # FE 에서 한글 치환하므로 원본 키 유지
_RULE_SOURCE_LABEL = {"vmd_default": "시스템 기본", "manual": "매뉴얼 지정"}
_DEAD_ZONE_KO = {
    "pillar": "기둥",
    "toilet": "화장실",
    "stair": "계단",
    "core": "코어",
    "electrical_panel": "분전반",
}

# 엔진 self-document: priority sort 로직 설명 (결정론적 backend 동작 투명 공개)
_PRIORITY_SORT_DOC = {
    "formula": "각 기물에 점수를 매긴 뒤, 점수가 높은 순으로 먼저 배치합니다. 점수가 같으면 작은 기물이 먼저 자리를 잡습니다.",
    "factors": [
        {
            "label": "기물 기본 중요도",
            "description": (
                "기물마다 매장 내 역할에 따라 기본 점수가 정해져 있습니다. "
                "공간을 나누는 가벽이나 브랜드 카운터처럼 핵심 역할 기물은 높은 기본 점수를, "
                "안내판·배너처럼 보조 기물은 낮은 점수를 받습니다."
            ),
        },
        {
            "label": "브랜드 매뉴얼 반영",
            "value": "+20점",
            "description": "브랜드 매뉴얼에서 '꼭 배치해달라'고 명시한 기물은 추가 점수를 받아 우선적으로 자리를 확보합니다.",
        },
        {
            "label": "공간 구조 앵커 보너스",
            "value": "+1000점",
            "description": (
                "가벽·포토존처럼 매장의 뼈대를 이루는 기물은 다른 기물 배치의 기준점이 되므로 "
                "압도적으로 높은 점수를 받아 가장 먼저 배치됩니다."
            ),
        },
        {
            "label": "같은 종류 기물 개수 제한",
            "description": "선반 계열, 진열대 계열 등 비슷한 용도의 기물이 한 공간에 몰리지 않도록 종류별 최대 개수를 제한합니다.",
        },
        {
            "label": "동점일 땐 작은 기물 우선",
            "description": "두 기물의 점수가 같다면, 공간을 덜 차지하는 기물을 먼저 배치해 전체 공간 효율을 확보합니다.",
        },
    ],
}

_DEFAULT_PATH_CRITERIA = {
    "mainArteryDescription": "입구에서 매장 안쪽까지 관통하는 주동선이 자동 생성되어 고객의 자연스러운 흐름을 확보합니다.",
    "zones": [
        {"key": "entrance_zone", "label": "Entrance · 감압 및 후킹 구역"},
        {"key": "mid_zone", "label": "Mid · 핵심 제품 관여 및 순환 구역"},
        {"key": "deep_zone", "label": "Deep · 목적지 및 백오피스 구역"},
    ],
    "subPathSupported": False,
}


def _debug_logs_root() -> str:
    """debug_logs 디렉토리 절대경로. 테스트에서 monkeypatch 가능하도록 분리."""
    return os.path.join(os.path.dirname(__file__), "..", "..", "debug_logs")


def build_report_json(state: dict) -> dict:
    """배치 state → AnalysisReportData 형태 직렬화.

    debug_logs 파일 없이 state 에서 직접 조립. place_service 에서 배치 완료 후 호출.
    반환값은 PlacementResult.reportJson (DB 저장) + 프론트 리포트 패널에 직접 전달.
    """
    from collections import Counter

    from app.utils import OBJECT_STANDARDS

    def name_of(obj_type: str) -> str:
        if obj_type == "*":
            return "모든 기물"
        if not obj_type:
            return ""
        std = OBJECT_STANDARDS.get(obj_type)
        return std["name"] if std and "name" in std else obj_type

    brand_data = state.get("brand_data") or {}
    placed_objects = state.get("placed_objects") or []
    dead_zones = state.get("dead_zones") or []
    token_summary = state.get("token_usage_summary") or {}
    eligible_objects = state.get("eligible_objects") or []
    pair_rules = brand_data.get("pair_rules") or []
    brand = brand_data.get("brand") or {}

    # ── 섹션 0: 입력 요약 (사용자가 준 값) ──────────────────────────
    usable_poly = state.get("usable_poly")
    area_m2 = round(usable_poly.area / 1_000_000, 1) if usable_poly else None

    entrances = state.get("entrances") or []
    if not entrances and state.get("entrance"):
        entrances = [state["entrance"]]

    sprinklers = state.get("sprinklers") or []

    clearspace_raw = brand.get("clearspace_mm") or {}
    clearspace_mm = clearspace_raw.get("value") if isinstance(clearspace_raw, dict) else clearspace_raw

    prohibited_raw = brand.get("prohibited_material") or {}
    prohibited_material = prohibited_raw.get("value") if isinstance(prohibited_raw, dict) else prohibited_raw

    ceiling_height_mm = state.get("ceiling_height_mm")
    input_summary = {
        "floor": {
            "areaMm2": round(usable_poly.area) if usable_poly else None,
            "areaM2": area_m2,
            "ceilingHeightMm": ceiling_height_mm,
            "entranceCount": len(entrances),
            "sprinklerCount": len(sprinklers),
            "deadZoneCount": len(dead_zones),
        },
        "brand": {
            "category": brand.get("brand_category") or state.get("brand_category") or "기타",
            "clearspaceMm": clearspace_mm,
            "prohibitedMaterial": prohibited_material,
            "hasBrandManual": bool(brand_data and brand),
        },
        "hasCrossSection": ceiling_height_mm is not None,
    }

    # ── 섹션 1: Overview ─────────────────────────────────────────
    summary = {
        "placedCount": len(placed_objects),
        "eligibleCount": len(eligible_objects) or len(placed_objects),
        "ruleCount": len(pair_rules),
        "deadZoneCount": len(dead_zones),
        "tokensInput": token_summary.get("total_input_tokens", 0),
        "tokensOutput": token_summary.get("total_output_tokens", 0),
        "costUsd": round(float(token_summary.get("estimated_cost_usd", 0.0)), 4),
        "durationSec": 0,
    }

    # ── 섹션 2: 배치 타임라인 (각 기물의 배치 근거) ───────────────
    placements = []
    for i, p in enumerate(placed_objects):
        ot = p.get("object_type", "")
        linked = []
        for r in pair_rules:
            a, b = r.get("object_a", ""), r.get("object_b", "")
            if a == ot and b != ot:
                target = b
            elif b == ot and a != ot:
                target = a
            else:
                continue
            linked.append({
                "target": target,
                "targetName": name_of(target),
                "relation": r.get("relation", "adjacent"),
                "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            })
        placed_because = p.get("placed_because", "")
        # "레퍼런스(IDOT)" 같은 내부 ID 포함 패턴 제거
        placed_because = re.sub(r'레퍼런스\s*\([^)]+\)', '', placed_because)
        # 남은 단독 "레퍼런스" 제거
        placed_because = re.sub(r'레퍼런스', '', placed_because)
        # 이중 공백·문두 조사 정리
        placed_because = re.sub(r'\s+', ' ', placed_because).strip()
        placements.append({
            "rank": i + 1,
            "objectType": ot,
            "name": name_of(ot),
            "placedBecause": placed_because,
            "linkedRules": linked[:3],
        })

    # ── 섹션 3: 제약 조건 ────────────────────────────────────────
    fire = brand_data.get("fire") or {}
    fire_regulation = {
        "mainCorridorMinMm": int(fire.get("main_corridor_min_mm", 900) or 900),
        "emergencyPathMinMm": int(fire.get("emergency_path_min_mm", 1200) or 1200),
    }

    construction = brand_data.get("construction") or {}
    clearance = {
        "wallClearanceMm": int(construction.get("wall_clearance_mm", 300) or 300),
        "objectGapMm": int(construction.get("object_gap_mm", 300) or 300),
    }

    dz_type_counts = Counter(
        dz.get("type", "other") if isinstance(dz, dict) else "obstacle"
        for dz in dead_zones
    )
    dead_zones_out = [
        {
            "type": dz_type,
            "label": f"{_DEAD_ZONE_KO.get(dz_type, '장애물')} {count}곳",
        }
        for dz_type, count in dz_type_counts.items()
    ]

    vmd_rules = []
    for r in pair_rules:
        a, b = r.get("object_a", ""), r.get("object_b", "")
        src = r.get("source")
        vmd_rules.append({
            "objectA": a,
            "objectAName": name_of(a),
            "objectB": b,
            "objectBName": name_of(b),
            "relation": r.get("relation", "adjacent"),
            "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            "source": src if src in ("vmd_default", "manual") else None,
        })

    ref_trace = state.get("ref_trace") or {}
    search = ref_trace.get("search") or {}
    reference_images = {
        "category": search.get("category") or brand.get("brand_category") or state.get("brand_category") or "기타",
        "source": search.get("source", "empty"),
        "count": int((search.get("search_stats") or {}).get("selected_count", 0) or 0),
    }

    return {
        "inputSummary": input_summary,
        "summary": summary,
        "placements": placements,
        "fireRegulation": fire_regulation,
        "pathCriteria": _DEFAULT_PATH_CRITERIA,
        "deadZones": dead_zones_out,
        "clearance": clearance,
        "vmdRules": vmd_rules,
        "referenceImages": reference_images,
        "prioritySort": _PRIORITY_SORT_DOC,
    }


def build_report_from_frontend(data: dict) -> dict:
    """프론트 보유 데이터로 AnalysisReportData 재생성.

    기존 프로젝트처럼 report_json 이 DB 에 없을 때 fallback 생성용.
    placed_objects / brand_data / dead_zones 등 프론트가 이미 로드한 값을 받아 조립.
    """
    from app.utils import OBJECT_STANDARDS

    def name_of(obj_type: str) -> str:
        if obj_type == "*":
            return "모든 기물"
        if not obj_type:
            return ""
        std = OBJECT_STANDARDS.get(obj_type)
        return std["name"] if std and "name" in std else obj_type

    def _val(field) -> object:
        if isinstance(field, dict):
            return field.get("value")
        return field

    placed_objects = data.get("placed_objects") or []
    failed_objects = data.get("failed_objects") or []
    dead_zones     = data.get("dead_zones") or []
    token_usage    = data.get("token_usage") or []
    brand_data     = data.get("brand_data") or {}
    area_m2        = data.get("area_m2")
    ceiling_height_mm = data.get("ceiling_height_mm")
    entrance_count = data.get("entrance_count", 0)
    sprinkler_count = data.get("sprinkler_count", 0)
    ref_quality_score = data.get("ref_quality_score")
    brand_category = data.get("brand_category") or brand_data.get("brand_category") or "기타"

    # pair_rules: brand_data 안에 있거나 별도 전달
    pair_rules = (brand_data.get("pair_rules")
                  or data.get("pair_rules")
                  or brand_data.get("placement_rules")
                  or [])

    # token 합산
    total_input  = sum(int(t.get("input_tokens") or 0) for t in token_usage)
    total_output = sum(int(t.get("output_tokens") or 0) for t in token_usage)

    # ── 입력 요약 ──────────────────────────────────────────────────
    brand = brand_data.get("brand") or brand_data  # brand sub-key 없으면 자체가 brand
    input_summary = {
        "floor": {
            "areaMm2": round(area_m2 * 1_000_000) if area_m2 else None,
            "areaM2": area_m2,
            "ceilingHeightMm": ceiling_height_mm,
            "entranceCount": entrance_count,
            "sprinklerCount": sprinkler_count,
            "deadZoneCount": len(dead_zones),
        },
        "brand": {
            "category": brand_category,
            "clearspaceMm": _val(brand.get("clearspace_mm")),
            "prohibitedMaterial": _val(brand.get("prohibited_material")),
            "hasBrandManual": bool(brand_data),
        },
        "hasCrossSection": ceiling_height_mm is not None,
    }

    # ── 개요 ──────────────────────────────────────────────────────
    summary = {
        "placedCount": len(placed_objects),
        "eligibleCount": len(placed_objects) + len(failed_objects),
        "ruleCount": len(pair_rules),
        "deadZoneCount": len(dead_zones),
        "tokensInput": total_input,
        "tokensOutput": total_output,
        "costUsd": 0.0,
        "durationSec": 0,
    }

    # ── 배치 타임라인 ─────────────────────────────────────────────
    placements = []
    for i, p in enumerate(placed_objects):
        ot = p.get("object_type", "")
        linked = []
        for r in pair_rules:
            a, b = r.get("object_a", ""), r.get("object_b", "")
            if a == ot and b != ot:
                target = b
            elif b == ot and a != ot:
                target = a
            else:
                continue
            linked.append({
                "target": target,
                "targetName": name_of(target),
                "relation": r.get("relation", "adjacent"),
                "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            })
        placed_because = re.sub(r'레퍼런스\s*\([^)]+\)', '', p.get("placed_because", ""))
        placed_because = re.sub(r'레퍼런스', '', placed_because)
        placed_because = re.sub(r'\s+', ' ', placed_because).strip()
        placements.append({
            "rank": i + 1,
            "objectType": ot,
            "name": name_of(ot),
            "placedBecause": placed_because,
            "linkedRules": linked[:3],
        })

    # ── 소방 / 이격 규정 ──────────────────────────────────────────
    fire = brand_data.get("fire") or {}
    fire_regulation = {
        "mainCorridorMinMm": int(fire.get("main_corridor_min_mm", 900) or 900),
        "emergencyPathMinMm": int(fire.get("emergency_path_min_mm", 1200) or 1200),
    }
    construction = brand_data.get("construction") or {}
    clearance = {
        "wallClearanceMm": int(construction.get("wall_clearance_mm", 300) or 300),
        "objectGapMm": int(construction.get("object_gap_mm", 300) or 300),
    }

    # ── 이격구역 집계 ─────────────────────────────────────────────
    dz_type_counts = Counter(
        dz.get("type", "other") if isinstance(dz, dict) else "obstacle"
        for dz in dead_zones
    )
    dead_zones_out = [
        {"type": t, "label": f"{_DEAD_ZONE_KO.get(t, '장애물')} {c}곳"}
        for t, c in dz_type_counts.items()
    ]

    # ── VMD 규칙 ──────────────────────────────────────────────────
    vmd_rules = []
    for r in pair_rules:
        a, b = r.get("object_a", ""), r.get("object_b", "")
        src = r.get("source")
        vmd_rules.append({
            "objectA": a, "objectAName": name_of(a),
            "objectB": b, "objectBName": name_of(b),
            "relation": r.get("relation", "adjacent"),
            "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            "source": src if src in ("vmd_default", "manual") else None,
        })

    # ── 레퍼런스 반영도 ───────────────────────────────────────────
    reference_images = {
        "category": brand_category,
        "source": "empty",
        "count": 0,
        "qualityScore": ref_quality_score,
    }

    return {
        "inputSummary": input_summary,
        "summary": summary,
        "placements": placements,
        "fireRegulation": fire_regulation,
        "pathCriteria": _DEFAULT_PATH_CRITERIA,
        "deadZones": dead_zones_out,
        "clearance": clearance,
        "vmdRules": vmd_rules,
        "referenceImages": reference_images,
        "prioritySort": _PRIORITY_SORT_DOC,
    }


def _build_report_data() -> dict | None:
    """debug_logs 최신 파일들을 조합하여 AnalysisReportData shape 로 반환.

    반환 값은 frontend/src/components/mypage/mockAnalysisReport.ts 의 AnalysisReportData
    TypeScript 타입과 필드 1:1 매칭. 타입 변경 시 양쪽 동시 갱신 필요.

    Returns:
        dict | None: debug_logs 비어있으면 None
    """
    base = _debug_logs_root()
    if not os.path.isdir(base):
        return None

    # 날짜 폴더 (YYYY-MM-DD 형식) 중 최신 탐색
    date_dirs = sorted(
        d for d in os.listdir(base)
        if os.path.isdir(os.path.join(base, d)) and d.startswith("20") and len(d) == 10
    )
    if not date_dirs:
        return None
    latest_dir = os.path.join(base, date_dirs[-1])

    def _load(fname: str) -> dict:
        p = os.path.join(latest_dir, fname)
        if not os.path.exists(p):
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"[report] {fname} 로드 실패: {e}")
            return {}

    brand_data = _load("brand_data.json")
    place_result = _load("place_result.json")
    object_selection = _load("object_selection_debug.json")
    dead_zones_data = _load("dead_zones_detail.json")
    ref_trace = _load("ref_trace.json")
    token_usage = _load("token_usage.json")

    if not place_result:
        return None  # 배치 실행 이력 없음

    # OBJECT_STANDARDS 에서 한글명 조회
    from app.utils import OBJECT_STANDARDS

    def name_of(obj_type: str) -> str:
        if obj_type == "*":
            return "모든 기물"
        if not obj_type:
            return ""
        std = OBJECT_STANDARDS.get(obj_type)
        return std["name"] if std and "name" in std else obj_type

    placed_objects = place_result.get("placed_objects", []) or []
    pair_rules = brand_data.get("pair_rules", []) or []
    dz_list = dead_zones_data.get("dead_zones", []) or []

    # Phase 1 — Overview
    summary = {
        "placedCount": len(placed_objects),
        "eligibleCount": object_selection.get("total_eligible_count", len(placed_objects)),
        "ruleCount": len(pair_rules),
        "deadZoneCount": len(dz_list),
        "tokensInput": token_usage.get("total_input_tokens", 0),
        "tokensOutput": token_usage.get("total_output_tokens", 0),
        "costUsd": round(float(token_usage.get("estimated_cost_usd", 0.0)), 4),
        "durationSec": 0,  # 현재 수집 로직 없음 — 후속 과제
    }

    # Phase 2 — 타임라인 (배치 사유 + 기물 근접 로직 통합)
    placements = []
    for i, p in enumerate(placed_objects):
        ot = p.get("object_type", "")
        linked = []
        for r in pair_rules:
            a, b = r.get("object_a", ""), r.get("object_b", "")
            if a == ot and b != ot:
                target = b
            elif b == ot and a != ot:
                target = a
            else:
                continue
            linked.append({
                "target": target,
                "targetName": name_of(target),
                "relation": r.get("relation", "adjacent"),
                "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            })
        placements.append({
            "rank": i + 1,
            "objectType": ot,
            "name": name_of(ot),
            "placedBecause": p.get("placed_because", ""),
            "linkedRules": linked[:3],  # UI 공간 상 상위 3개만 노출
        })

    # Phase 3 — 소방법
    fire = brand_data.get("fire", {}) or {}
    fire_regulation = {
        "mainCorridorMinMm": int(fire.get("main_corridor_min_mm", 900) or 900),
        "emergencyPathMinMm": int(fire.get("emergency_path_min_mm", 1200) or 1200),
    }

    # Phase 3 — 이격
    construction = brand_data.get("construction", {}) or {}
    clearance = {
        "wallClearanceMm": int(construction.get("wall_clearance_mm", 300) or 300),
        "objectGapMm": int(construction.get("object_gap_mm", 300) or 300),
    }

    # Phase 3 — deadZones 집계 (type 별 카운트)
    dz_type_counts = Counter(dz.get("type", "other") for dz in dz_list)
    dead_zones_out = [
        {
            "type": dz_type,
            "label": f"{_DEAD_ZONE_KO.get(dz_type, '장애물')} {count}곳",
        }
        for dz_type, count in dz_type_counts.items()
    ]

    # Phase 3 — vmdRules (FE 타입과 일치: objectAName / objectBName / source 한글 포함)
    vmd_rules = []
    for r in pair_rules:
        a, b = r.get("object_a", ""), r.get("object_b", "")
        src = r.get("source")
        vmd_rules.append({
            "objectA": a,
            "objectAName": name_of(a),
            "objectB": b,
            "objectBName": name_of(b),
            "relation": r.get("relation", "adjacent"),
            "minGapMm": int(r.get("min_gap_mm", 0) or 0),
            # FE 에서 RULE_SOURCE_LABEL 로 재치환 — 여기선 raw 유지 (schema 안정성)
            "source": src if src in ("vmd_default", "manual") else None,
        })

    # Phase 3 — referenceImages
    search = ref_trace.get("search", {}) or {}
    reference_images = {
        "category": search.get("category", "기타"),
        "source": search.get("source", "empty"),
        "count": int(search.get("search_stats", {}).get("selected_count", 0) or 0),
    }

    return {
        "summary": summary,
        "placements": placements,
        "fireRegulation": fire_regulation,
        "pathCriteria": _DEFAULT_PATH_CRITERIA,
        "deadZones": dead_zones_out,
        "clearance": clearance,
        "vmdRules": vmd_rules,
        "referenceImages": reference_images,
        "prioritySort": _PRIORITY_SORT_DOC,
    }
