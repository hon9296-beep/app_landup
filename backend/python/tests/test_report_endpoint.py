"""
/api/report/latest endpoint + _build_report_data() 검증.

목적:
  - debug_logs/YYYY-MM-DD/ 의 JSON 파일들이 FE AnalysisReportData 스키마에 1:1 매핑되는지
  - 누락 파일 (fire 정보 없음 등) 시 기본값 fallback 동작
  - placements[i].linkedRules 가 pair_rules 와 정확 매칭
  - dead_zones type 카운트 집계

FE contract: frontend/src/components/mypage/mockAnalysisReport.ts AnalysisReportData
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api import _build_report_data


# ── 테스트용 fixture 디렉토리 생성 ──────────────────────────────────

def _make_debug_logs(
    tmp_path: Path,
    *,
    place_result: dict | None = None,
    brand_data: dict | None = None,
    object_selection: dict | None = None,
    dead_zones: dict | None = None,
    ref_trace: dict | None = None,
    token_usage: dict | None = None,
    date_dir: str = "2026-04-23",
) -> Path:
    """tmp_path 안에 debug_logs/YYYY-MM-DD/ 구조 생성."""
    base = tmp_path / "debug_logs" / date_dir
    base.mkdir(parents=True, exist_ok=True)

    files = {
        "place_result.json": place_result or {},
        "brand_data.json": brand_data or {},
        "object_selection_debug.json": object_selection or {},
        "dead_zones_detail.json": dead_zones or {},
        "ref_trace.json": ref_trace or {},
        "token_usage.json": token_usage or {},
    }
    for fname, data in files.items():
        if data:
            (base / fname).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    return base


def _patch_debug_logs_path(tmp_path: Path):
    """_build_report_data 가 사용하는 debug_logs root 를 tmp 로 redirect.

    patch 타깃은 정의 모듈 (app.services.report_service). api.py 재노출은
    이름 바인딩 복사라 그쪽을 patch 해도 내부 호출에는 반영되지 않음.
    """
    return patch("app.services.report_service._debug_logs_root", return_value=str(tmp_path / "debug_logs"))


# ── Happy path ────────────────────────────────────────────────────

def test_full_report_assembly(tmp_path: Path):
    """전체 8 섹션이 정상 조립되는지."""
    _make_debug_logs(
        tmp_path,
        place_result={
            "placed_objects": [
                {"object_type": "counter", "placed_because": "deep_zone 측면 벽으로 전진 배치"},
                {"object_type": "display_table", "placed_because": "mid_zone 중앙 노출"},
            ]
        },
        brand_data={
            "fire": {"main_corridor_min_mm": 900, "emergency_path_min_mm": 1200},
            "construction": {"wall_clearance_mm": 300, "object_gap_mm": 300},
            "pair_rules": [
                {"object_a": "counter", "object_b": "*", "relation": "separate", "min_gap_mm": 1200, "source": "vmd_default"},
                {"object_a": "display_table", "object_b": "display_table", "relation": "separate", "min_gap_mm": 600, "source": "vmd_default"},
            ],
        },
        object_selection={"total_eligible_count": 3},
        dead_zones={
            "dead_zones": [
                {"type": "pillar", "center_mm": [1000, 1000]},
                {"type": "pillar", "center_mm": [2000, 2000]},
                {"type": "toilet", "center_mm": [3000, 3000]},
            ]
        },
        ref_trace={
            "search": {
                "category": "뷰티·코스메틱",
                "source": "local_cache",
                "search_stats": {"selected_count": 4},
            }
        },
        token_usage={
            "total_input_tokens": 11990,
            "total_output_tokens": 4619,
            "estimated_cost_usd": 0.1192,
        },
    )

    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()

    assert report is not None

    # Phase 1 Summary
    assert report["summary"]["placedCount"] == 2
    assert report["summary"]["eligibleCount"] == 3
    assert report["summary"]["ruleCount"] == 2
    assert report["summary"]["deadZoneCount"] == 3
    assert report["summary"]["tokensInput"] == 11990
    assert report["summary"]["costUsd"] == pytest.approx(0.1192)

    # Phase 2 placements
    assert len(report["placements"]) == 2
    assert report["placements"][0]["rank"] == 1
    assert report["placements"][0]["objectType"] == "counter"
    assert report["placements"][0]["name"] == "계산대"  # OBJECT_STANDARDS 한글명
    assert report["placements"][0]["placedBecause"] == "deep_zone 측면 벽으로 전진 배치"
    # counter 의 linkedRules: pair_rules 에서 counter 와 매칭되는 1건
    assert len(report["placements"][0]["linkedRules"]) == 1
    assert report["placements"][0]["linkedRules"][0]["target"] == "*"
    assert report["placements"][0]["linkedRules"][0]["targetName"] == "모든 기물"

    # Phase 3
    assert report["fireRegulation"]["mainCorridorMinMm"] == 900
    assert report["clearance"]["wallClearanceMm"] == 300
    assert report["referenceImages"]["category"] == "뷰티·코스메틱"
    assert report["referenceImages"]["count"] == 4

    # deadZones 집계 (type 별 count)
    dz_by_type = {d["type"]: d["label"] for d in report["deadZones"]}
    assert "기둥 2곳" in dz_by_type["pillar"]
    assert "화장실 1곳" in dz_by_type["toilet"]

    # vmdRules — Korean names 자동 적용
    assert len(report["vmdRules"]) == 2
    rule0 = report["vmdRules"][0]
    assert rule0["objectAName"] == "계산대"
    assert rule0["objectBName"] == "모든 기물"
    assert rule0["source"] == "vmd_default"

    # prioritySort + pathCriteria — 백엔드 self-document 텍스트 포함
    assert "formula" in report["prioritySort"]
    assert len(report["prioritySort"]["factors"]) == 5
    assert report["pathCriteria"]["subPathSupported"] is False


# ── Edge cases ────────────────────────────────────────────────────

def test_returns_none_when_no_debug_logs(tmp_path: Path):
    """debug_logs 디렉토리 자체 없으면 None."""
    with _patch_debug_logs_path(tmp_path):
        result = _build_report_data()
    assert result is None


def test_returns_none_when_no_date_folders(tmp_path: Path):
    """debug_logs 는 있지만 날짜 폴더 없으면 None."""
    (tmp_path / "debug_logs").mkdir()
    with _patch_debug_logs_path(tmp_path):
        result = _build_report_data()
    assert result is None


def test_returns_none_when_no_place_result(tmp_path: Path):
    """배치 실행 이력(place_result.json) 없으면 None."""
    _make_debug_logs(tmp_path, brand_data={"fire": {"main_corridor_min_mm": 900}})
    with _patch_debug_logs_path(tmp_path):
        result = _build_report_data()
    assert result is None


def test_fallback_defaults_when_brand_data_partial(tmp_path: Path):
    """brand_data 일부만 있을 때 누락 필드는 기본값 적용."""
    _make_debug_logs(
        tmp_path,
        place_result={"placed_objects": [{"object_type": "counter", "placed_because": "test"}]},
        brand_data={},  # fire/construction/pair_rules 전부 없음
    )
    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()

    assert report is not None
    assert report["fireRegulation"]["mainCorridorMinMm"] == 900  # 기본값
    assert report["clearance"]["wallClearanceMm"] == 300
    assert report["vmdRules"] == []


def test_unknown_object_type_falls_back_to_raw(tmp_path: Path):
    """OBJECT_STANDARDS 미등록 타입은 raw object_type 그대로 노출."""
    _make_debug_logs(
        tmp_path,
        place_result={"placed_objects": [{"object_type": "unknown_xyz", "placed_because": ""}]},
    )
    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()
    assert report["placements"][0]["name"] == "unknown_xyz"


def test_unknown_dead_zone_type_uses_raw_label(tmp_path: Path):
    """electrical_panel / 새로운 타입도 fallback 라벨로 표시."""
    _make_debug_logs(
        tmp_path,
        place_result={"placed_objects": [{"object_type": "counter"}]},
        dead_zones={
            "dead_zones": [
                {"type": "electrical_panel", "center_mm": [0, 0]},
                {"type": "unknown_new_type", "center_mm": [0, 0]},
            ]
        },
    )
    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()

    dz_by_type = {d["type"]: d["label"] for d in report["deadZones"]}
    assert "분전반 1곳" in dz_by_type["electrical_panel"]
    assert "unknown_new_type 1곳" in dz_by_type["unknown_new_type"]


def test_linked_rules_excludes_self_self_pairs(tmp_path: Path):
    """object_a == object_b 인 룰 (예: display_table x display_table) 은 linkedRules 에 들어가도 됨."""
    _make_debug_logs(
        tmp_path,
        place_result={"placed_objects": [{"object_type": "display_table", "placed_because": ""}]},
        brand_data={
            "pair_rules": [
                {"object_a": "display_table", "object_b": "display_table", "relation": "separate", "min_gap_mm": 600},
            ],
        },
    )
    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()

    # object_a == object_b 케이스 — 우리 로직은 이걸 self-self 로 보고 linkedRules 에 안 넣음
    # (a == ot and b != ot) AND (b == ot and a != ot) 둘 다 거짓
    assert report["placements"][0]["linkedRules"] == []


def test_linked_rules_top_3_cap(tmp_path: Path):
    """linkedRules 는 상위 3개로 제한 (UI 공간)."""
    _make_debug_logs(
        tmp_path,
        place_result={"placed_objects": [{"object_type": "counter", "placed_because": ""}]},
        brand_data={
            "pair_rules": [
                {"object_a": "counter", "object_b": f"target_{i}", "relation": "separate", "min_gap_mm": 100}
                for i in range(5)
            ],
        },
    )
    with _patch_debug_logs_path(tmp_path):
        report = _build_report_data()

    assert len(report["placements"][0]["linkedRules"]) == 3
