"""
B-3 후속 후속 (#535 후속) — 가벽 부착 obj 의 back 이격 무시.

진규님 5-8 진단:
  "오브젝트 이격때문에 가벽에 안붙거나 하면 가벽으로 붙을땐 이격 X join_with 랑 같은 개념"

회귀 시점: 5-8 12:48 라이브 fail 사유에 "전후 이격 내 장애물 (back, dead zone)" 반복 발생.
원인: placement 의 전후 이격 검사가 `static_cache` (가벽 포함) 와의 충돌 검출 → reject.
즉 LLM 이 가벽 면 ref 매핑해도 placement 가 가벽을 장애물로 취급해 obj 못 박음.

fix:
  _validate_placement signature 에 is_partition_attached 인자 추가.
  ref_point 의 is_partition=True 일 때 호출자가 True 전달 → back 이격 검사 skip.
  front 이격은 유지 (고객 응대 영역 보호).

회귀 차단:
  - signature 에 인자 정의
  - 호출자 2곳 (ref 직접 시도 + slot fallback) 모두 전달
  - back 방향만 skip — front 보호
  - ref_point.is_partition 키 활용 (partition_placement 가 박은 face ref)
"""
import inspect

from app.nodes_small import placement


# ── signature ───────────────────────────────────────────────


def test_validate_placement_has_is_partition_attached_param():
    """_validate_placement 가 is_partition_attached 인자 받음."""
    sig = inspect.signature(placement._validate_placement)
    assert "is_partition_attached" in sig.parameters, (
        "_validate_placement 에 is_partition_attached 인자 누락"
    )


def test_validate_placement_default_false():
    """is_partition_attached default = False (기존 호출 호환)."""
    sig = inspect.signature(placement._validate_placement)
    assert sig.parameters["is_partition_attached"].default is False


# ── 호출자 — 두 위치 모두 전달 ─────────────────────────────


def test_callers_pass_is_partition_attached():
    """placement.run 의 _validate_placement 호출 2곳 모두 is_partition_attached 전달."""
    src = inspect.getsource(placement)
    # 호출 횟수
    call_count = src.count("_validate_placement(")
    # 2곳 (ref 직접 + slot fallback) + 정의 1줄 = 3
    assert call_count >= 3, f"_validate_placement 호출 누락 — 발견 {call_count}회"
    # 인자 전달 횟수 (호출 시 명시)
    pass_count = src.count("is_partition_attached=bool(rp.get")
    assert pass_count == 2, (
        f"is_partition_attached 전달 누락 — 발견 {pass_count}회 (예상 2회)"
    )


# ── 분기 로직 — back 만 skip, front 유지 ─────────────────


def test_skip_logic_back_only():
    """이격 검사 분기 — back 방향만 skip, front 는 유지."""
    src = inspect.getsource(placement._validate_placement)
    # 분기 조건 명시
    assert 'is_partition_attached and dir_name == "back"' in src, (
        "분기 조건 누락 — back 방향만 skip 해야 함"
    )
    # front 는 유지 (continue 안 함)
    # 즉 분기 후 continue 만 있고 front 분기는 별도 처리 X


# ── ref_point.is_partition 키 활용 ───────────────────────


def test_partition_face_ref_has_is_partition_flag():
    """partition_placement 가 박는 face ref 에 is_partition=True 플래그.

    placement 가 이 플래그로 가벽 부착 의도 식별.
    """
    from app.nodes_small import partition_placement
    src = inspect.getsource(partition_placement)
    assert 'nrp["is_partition"] = True' in src, (
        "partition_placement 가 face ref 에 is_partition 플래그 안 박음"
    )


# ── 회귀 가드 ─────────────────────────────────────────────


def test_no_legacy_back_clearance_check_for_partition():
    """가벽 부착 obj 의 back 이격 검사 회귀 차단.

    이전: ref 의 is_partition 무시 → back 이격에서 가벽이 static_cache 침범 → reject
    fix: is_partition_attached=True 면 back 이격 skip
    """
    src = inspect.getsource(placement._validate_placement)
    # back 이격 분기 + skip 둘 다 존재
    assert "전후 이격 내 장애물" in src  # 기존 검사 메시지 유지
    assert 'is_partition_attached and dir_name == "back"' in src
    assert "continue" in src  # skip 로직
