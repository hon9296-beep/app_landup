"""
I-7 / 2026-04-23 — fallback 경로 placed_because 자연어 템플릿 검증.

배경:
  design LLM 스킵 시 (ref 이미지 부재 / API 실패 / 신규 카테고리) _default_intents 가
  placed_because 를 생성함. 기존엔 "side_wall → photo_wall (wall_facing)" 같은
  개발자 포맷이 사용자에게 그대로 노출되던 문제를 한글 자연어 템플릿으로 교체.

검증 범위:
  - Zone + Label + direction 정상 조합 시 기대 한글 문장 생성
  - OBJECT_STANDARDS 미등록 오브젝트는 raw object_type 그대로 사용
  - ref_point 매칭 실패 시 zone/label 공백 → "기본 배치" 문구로 graceful degrade
  - 미등록 라벨/존/방향도 raw 그대로 노출 (mapping miss 시 crash 안 함)
"""
from app.nodes_small.design import (
    _build_fallback_placed_because,
    _ko_object_name,
)


# ── 정상 조합 케이스 ──────────────────────────────────────────────

def test_full_natural_sentence():
    """등록된 object_type + 알려진 zone/label/direction."""
    result = _build_fallback_placed_because(
        "counter", "deep_zone", "deep_wall", "wall_facing"
    )
    assert result == "안쪽 구역의 후면 벽에 계산대 배치 — 벽 부착"


def test_center_island_pattern():
    """display_table + center_freestanding + center."""
    result = _build_fallback_placed_because(
        "display_table", "mid_zone", "center_freestanding", "center"
    )
    assert result == "중간 구역의 매장 중앙에 진열대 배치 — 중앙 아일랜드형"


def test_entrance_adjacent_focal():
    """banner_stand 류 입구 인접 + focal."""
    result = _build_fallback_placed_because(
        "banner_stand", "entrance_zone", "entrance_adjacent", "focal"
    )
    assert result == "입구 구역의 입구 인접에 배너 배치 — 시선 집중 지점"


def test_photo_wall_side_wall():
    result = _build_fallback_placed_because(
        "photo_wall", "mid_zone", "side_wall", "wall_facing"
    )
    assert result == "중간 구역의 측면 벽에 포토월 배치 — 벽 부착"


# ── ref_point 매칭 실패 (zone/label 빈 값) ──────────────────────

def test_no_ref_point_fallback():
    """zone/label 공백 시 '기본 배치' 문구로 degrade."""
    result = _build_fallback_placed_because("counter", "", "", "wall_facing")
    assert result == "계산대 기본 배치 — 벽 부착"


def test_zone_only_no_label():
    """zone 은 있는데 label 만 빈 경우."""
    result = _build_fallback_placed_because("counter", "mid_zone", "", "wall_facing")
    assert result == "중간 구역에 계산대 배치 — 벽 부착"


# ── OBJECT_STANDARDS 미등록 객체 ────────────────────────────────

def test_unregistered_object_type_passthrough():
    """OBJECT_STANDARDS 에 없는 타입 (예: fitting_room) 은 raw ID 사용."""
    # fitting_room 은 worklist I-4 등록 예정, 현재 미등록
    result = _build_fallback_placed_because(
        "fitting_room", "deep_zone", "deep_wall", "wall_facing"
    )
    assert "fitting_room" in result
    assert result.startswith("안쪽 구역의 후면 벽에")


def test_ko_object_name_known():
    assert _ko_object_name("counter") == "계산대"
    assert _ko_object_name("photo_wall") == "포토월"
    assert _ko_object_name("partition_wall_I") == "가벽(일자형)"


def test_ko_object_name_unknown_returns_raw():
    assert _ko_object_name("not_registered_xyz") == "not_registered_xyz"


# ── Unknown 라벨/존/방향 처리 (mapping miss graceful) ─────────

def test_unknown_zone_passes_through():
    """신규 zone label 은 raw 그대로 (crash 안 함)."""
    result = _build_fallback_placed_because(
        "counter", "unknown_zone_xyz", "side_wall", "wall_facing"
    )
    assert "unknown_zone_xyz" in result
    assert "측면 벽" in result
    assert "계산대" in result
    assert "벽 부착" in result


def test_unknown_direction_passes_through():
    result = _build_fallback_placed_because(
        "counter", "mid_zone", "side_wall", "unknown_direction"
    )
    assert result.endswith("— unknown_direction")


# ── 개발자 포맷 제거 확증 (회귀 방지) ─────────────────────────

def test_no_dev_format_artifacts():
    """이전 포맷 잔재 (→ 화살표, 파이썬 식별자 raw) 가 나타나지 않아야 함."""
    result = _build_fallback_placed_because(
        "counter", "deep_zone", "deep_wall", "wall_facing"
    )
    # 기존 dev 포맷에 있던 특징 검증
    assert "side_wall" not in result
    assert "deep_wall" not in result  # 영문 ID 노출 금지
    assert "wall_facing" not in result
    assert "counter" not in result  # Korean name 이어야 함
    # 자연어 마커는 있어야 함
    assert "의" in result  # 조사
    assert "에" in result
    assert "배치" in result
