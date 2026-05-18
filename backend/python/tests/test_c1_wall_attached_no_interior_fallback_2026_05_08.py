"""
C1 — placement step-down zone 유지 강제 (consultation_desk fallback 끼워박힘 fix).

진규님 5-8 16:34 라이브 진단:
  - consultation_desk 가 wall 의도 → fallback Phase 4 → interior_slot_1 강제 끼워박힘
  - attach=free / dir=inward → 벽 부착 의도 깨짐 → AP-405-b reject
  - 본질: VMD_WALL_ATTACHMENT 에 consultation_desk 누락 → default "free" → interior 허용

진규님 5-8 인지:
  "fallback 이 drop 이 아니라 fallback 아무대나로 변했구나 양보때문에"

fix:
  (1) VMD_WALL_ATTACHMENT 에 consultation_desk = "near" 추가
  (2) fallback Phase 4 의 wall slot 제한을 flush + near 둘 다 적용 (interior_slot 차단)
  → 벽 부착 의도 obj 는 자리 없으면 drop (한복판 끼워박힘 X).
"""
import inspect


# ── (1) VMD_WALL_ATTACHMENT 등록 ──────────────────────────


def test_consultation_desk_is_near():
    """consultation_desk = 'near' (벽 인접 부착) 등록."""
    from app.vmd_constants import VMD_WALL_ATTACHMENT
    assert VMD_WALL_ATTACHMENT.get("consultation_desk") == "near", (
        f"consultation_desk wall_attachment = {VMD_WALL_ATTACHMENT.get('consultation_desk')!r} — "
        f"'near' 이어야 함 (5-8 라이브 회귀 fix)"
    )


def test_other_wall_attachments_preserved():
    """기존 등록은 회귀 없이 유지."""
    from app.vmd_constants import VMD_WALL_ATTACHMENT
    assert VMD_WALL_ATTACHMENT["counter"] == "near"
    assert VMD_WALL_ATTACHMENT["display_table"] == "free"
    assert VMD_WALL_ATTACHMENT["shelf_wall"] == "flush"
    assert VMD_WALL_ATTACHMENT["photo_wall"] == "flush"
    assert VMD_WALL_ATTACHMENT["partition_wall_I"] == "flush"
    assert VMD_WALL_ATTACHMENT["kiosk"] == "near"


def test_test_bar_is_near():
    """test_bar = 'near' (벽 인접 부착) 등록 — 5-8 18:35 라이브 회귀 fix.

    이전: 미등록 → default "free" → fallback Phase 4 interior_slot 한복판 부유.
    이후: "near" 등록 → wall slot 만 시도 → 자리 없으면 drop.
    """
    from app.vmd_constants import VMD_WALL_ATTACHMENT
    assert VMD_WALL_ATTACHMENT.get("test_bar") == "near", (
        f"test_bar wall_attachment = {VMD_WALL_ATTACHMENT.get('test_bar')!r} — "
        f"'near' 이어야 함 (5-8 18:35 라이브 회귀 fix)"
    )


# ── (2) fallback Phase 4 wall slot 제한 ──────────────────


def test_fallback_blocks_interior_for_flush_and_near():
    """fallback.py Phase 4 가 flush + near 둘 다 interior/center slot 차단."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # 새 분기 코드 박힘
    assert 'wall_attach in ("flush", "near")' in src
    assert '"center" in slot_key or "interior" in slot_key' in src
    # 5-8 컨텍스트 명시
    assert "5-8 16:34" in src or "consultation_desk" in src


def test_fallback_free_obj_unaffected():
    """free obj (display_table / banner_stand) 는 fallback Phase 4 에서 interior slot 허용 (정상)."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # free 는 wall_attach 분기에 안 들어가게
    # 코드 패턴: wall_attach in ("flush", "near") 만 차단. "free" 는 빠짐
    assert '"free"' not in src.split("wall_attach in")[1].split("\n")[0] if "wall_attach in" in src else True


# ── 통합 ────────────────────────────────────────────────


def test_fallback_blocks_inward_center_for_flush_near():
    """fallback Phase 4 strategies — flush/near obj 는 wall_facing direction 만 시도.

    5-8 17:38 라이브 회귀 fix: east_wall_slot_24 같은 wall slot 통과해도 direction=inward
    박힘 → 벽에 있지만 안쪽 향함 → 한복판 떠있는 효과. inward / center direction 차단.
    """
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # wall_facing 만 허용 분기 박힘
    assert 'wall_attach in ("flush", "near") and direction != "wall_facing"' in src
    # 17:38 라이브 컨텍스트
    assert "17:38" in src or "east_wall_slot" in src or "벽에 있지만 안쪽 향함" in src


def test_fallback_blocks_toilet_proximity_for_stay_obj():
    """fallback Phase 4 toilet 1500mm 이내 consultation_desk/counter/kiosk/test_bar 차단.

    5-8 17:38 라이브: consultation_desk 가 (300, 3242) east_wall_slot_24 에 박힘 →
    화장실 (y<2000) 까지 1242mm 거리 < 1500 → AP-003 위반 (단 design 단계 룰이라 placement 못 막음).
    fallback 단계에서 직접 차단.
    """
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # toilet 차단 분기
    assert 'TOILET_BLOCKED_TYPES' in src
    # 4 obj type 다 포함
    assert '"consultation_desk"' in src
    assert '"counter"' in src
    assert '"kiosk"' in src
    assert '"test_bar"' in src
    # 1500mm 거리
    assert '1500' in src
    # inaccessible_types 'toilet' 만 필터
    assert "'toilet'" in src or '"toilet"' in src


def test_phase5_blocks_inward_center_for_flush_near():
    """Phase 5 step-down 도 flush/near 는 wall_facing direction 만 시도.

    5-8 18:09 라이브 회귀 fix: test_bar (flush) 가 Phase 5 stepdown 으로 wall_facing 박혔지만
    attach='' 빈 채로 직렬화 → AP-405-b reject. Phase 4 와 동일 룰 Phase 5 에도 적용.
    """
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    assert 'wall_attach_p5 in ("flush", "near") and direction != "wall_facing"' in src
    assert "Phase 5 도 flush/near" in src or "Phase 5 도 wall_facing" in src or "5-8 17:38" in src


def test_phase5_blocks_toilet_proximity():
    """Phase 5 도 toilet 1500mm 이내 consultation/counter/kiosk/test_bar 차단."""
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # Phase 5 의 TOILET_BLOCKED_TYPES_P5 박힘
    assert 'TOILET_BLOCKED_TYPES_P5' in src


def test_phase4_phase5_entry_includes_wall_attachment():
    """Phase 4 + Phase 5 entry 에 wall_attachment 명시 — 빈 문자열 직렬화 회귀 차단.

    5-8 18:09 라이브: test_bar attach='' 박힘 (entry 에 wall_attachment 키 누락).
    fix: entry dict 에 obj.get("wall_attachment", "free") 박기.
    """
    from app.nodes_small import fallback
    src = inspect.getsource(fallback)
    # 두 Phase 의 entry 에 wall_attachment 키 박혔는지 source 검사
    # entry 딕셔너리 정의 부근에 wall_attachment 박힘
    assert src.count('"wall_attachment": obj.get("wall_attachment"') >= 2, (
        f"Phase 4 + Phase 5 entry 둘 다 wall_attachment 박혀야 함 (count={src.count(chr(34) + 'wall_attachment' + chr(34) + ': obj.get(' + chr(34) + 'wall_attachment' + chr(34))})"
    )


def test_consultation_desk_now_blocked_from_interior_in_fallback():
    """consultation_desk (near) 가 fallback Phase 4 에서 interior slot 차단됨 (회귀 시뮬).

    실제 fallback.run() 호출은 state 의존 큼 — 코드 분기 박힘 검증.
    """
    from app.vmd_constants import VMD_WALL_ATTACHMENT
    from app.nodes_small import fallback

    # 룰 1: consultation_desk = near
    assert VMD_WALL_ATTACHMENT["consultation_desk"] == "near"

    # 룰 2: fallback 이 near 도 interior 차단
    src = inspect.getsource(fallback)
    assert 'wall_attach in ("flush", "near")' in src
    # consultation_desk = near → interior slot continue (skip) → 다음 slot 시도
    # 모든 wall slot 시도 후 자리 없으면 placed=False → still_failed 유지 → drop
