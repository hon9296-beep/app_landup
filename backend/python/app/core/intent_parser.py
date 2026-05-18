"""
intent_parser.py — 사용자 요구사항 자연어 → 구조화된 배치 액션 변환

[설계 원칙]
- LLM(Haiku)에게 실제 ref_points 목록과 기존 배치 현황을 보여줌
- LLM이 zone_hint / direction_hint를 직접 결정 (추상 방향 → 코드 매핑 제거)
- 출력: actions 리스트 (add / remove)
- ref_point 최종 선택은 design.py(Sonnet)가 공간 전체 맥락에서 수행

[기존 대비 변경]
- _determine_entrance_side / _find_ref_by_wall 등 취약한 코드 매핑 제거
- ResolvedIntent dataclass 유지 (api.py / design.py 인터페이스 호환)
- is_removal, quantity, zone_hint, original_text 필드 유지
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class IntentParseError(Exception):
    """LLM 호출 실패 — 크레딧 소진·인증 오류·네트워크 등. 기존 배치 유지 트리거."""
    pass


# ──────────────────────────────────────────────
# 데이터 구조 (기존 인터페이스 유지)
# ──────────────────────────────────────────────

@dataclass
class ResolvedIntent:
    """
    Intent Parser 출력 구조.

    - action="add"     : 배치 요청  → design.py가 ref_point 선택
    - action="remove"  : 제거 요청  → _apply_removal_intents 처리
    - action="resize"  : 크기 변경  → _apply_resize_intents 처리
    - action="reorient": 방향 변경  → _apply_reorient_intents 처리
    - zone_hint        : design.py 배치 존 가이드 (entrance_zone / mid_zone / deep_zone)
    - direction_hint   : design.py 방향 가이드 (wall_facing / center / focal)
    - quantity=-1      : "최대한 채워달라" fill 요청
    - size_modifier    : resize 액션에만 적용 (larger / smaller / max / min)
    - scope            : reorient 액션에 적용 ("all" = 전체, "type" = 특정 타입)
    """
    action: str = "add"                      # add / remove / resize / reorient
    object_type: str = ""
    quantity: int = 1                        # -1 = fill
    zone_hint: Optional[str] = None          # entrance_zone / mid_zone / deep_zone
    direction_hint: Optional[str] = None     # wall_facing / center / focal
    original_text: str = ""
    is_removal: bool = False                 # 하위 호환 (action=="remove"와 동일)
    size_modifier: Optional[str] = None      # larger / smaller / max / min
    scope: str = "type"                      # "type" | "all"
    wall_hint: Optional[str] = None          # "right" | "left" | "center" — 입구 기준 상대 방위


# ──────────────────────────────────────────────
# LLM 프롬프트
# ──────────────────────────────────────────────

_SYSTEM = """당신은 팝업스토어 공간 배치 요구사항 파서입니다.
사용자 요구사항 텍스트를 분석해 배치/제거/크기변경/방향변경 액션 목록을 JSON으로 반환하세요.

## 오브젝트 타입 코드 (이 코드만 사용)
- counter               : 카운터, 계산대, POS
- display_table         : 진열대, 상품진열대, 전시대, 디스플레이 테이블
- display_table_standard: 표준 진열대, 표준형 테이블
- character_bbox        : 캐릭터 조형물, 등신대, 캐릭터 인형, 캐릭터 피규어
- photo_wall            : 포토월, 포토 배경, 배경 패널, 그래픽 월, 포토존 배경
- photo_island          : 포토존, 포토 존, 사진존, 360 포토, 포토 아일랜드
- shelf_wall            : 벽면 선반, 벽선반, 렌탈 선반
- shelf_standard        : 표준 선반
- shelf_3tier           : 3단선반, 다단 선반
- test_bar              : 시연대, 테스팅 바, 체험대
- consultation_desk     : 상담 데스크, 상담대, 컨설테이션 데스크
- banner_stand          : 배너, 배너 스탠드, 현수막 스탠드
- partition_wall_I      : 일자 가벽, 백월, 파티션, 일자형 가벽
- partition_wall_L      : ㄱ자 가벽, 코너 가벽, ㄱ자형 가벽, 간이창고
- signage_stand         : 안내판, A보드, 입간판
- kiosk                 : 키오스크, 무인결제기

## 액션 규칙
action "add"      : 새로 배치 요청
action "remove"   : 제거/치우기 요청 ("빼달라", "없애", "치워", "제거해")
action "resize"   : 크기 변경 요청 ("크게", "작게", "더 크게", "키워", "줄여", "넓게", "좁게")
action "reorient" : 방향(direction)만 전환 ("향하게", "바라보게", "방향 바꿔", "중앙 보도록", "입구 보도록")

## 이동 요청 파싱 규칙 (중요)
"옮겨줘", "이동해줘", "~쪽으로 가져와", "~으로 이동", "위치 바꿔줘" 처럼
위치(zone) 변경을 요청하면 반드시 remove + add 쌍으로 파싱하세요. reorient 사용 금지.
예: "계산대를 입구쪽으로 옮겨줘"
→ [
    {"action":"remove","object_type":"counter","quantity":1,...},
    {"action":"add","object_type":"counter","quantity":1,"zone_hint":"entrance_zone","direction_hint":"focal",...}
  ]
예: "진열대를 벽쪽으로 옮겨줘"
→ [
    {"action":"remove","object_type":"display_table","quantity":1,...},
    {"action":"add","object_type":"display_table","quantity":1,"direction_hint":"wall_facing",...}
  ]

## 수량 규칙
- 숫자 명시 → 그대로
- "최대한", "가득", "채워", "전부", "빼곡히" → -1
- 제거/크기변경/방향전환 시 "전부", "다", "모두" → -1

## zone_hint 규칙 (add 액션에만 적용)
- "entrance_zone" : 입구 근처, 입구 쪽, 앞쪽
- "mid_zone"      : 중간, 가운데 쪽
- "deep_zone"     : 안쪽, 깊은 곳, 뒤쪽
- null            : 위치 언급 없음

## direction_hint 규칙 (add / reorient 액션에 적용)
- "wall_facing" : 벽 쪽에, 벽면에, 벽에 붙여서
- "center"      : 중앙에, 가운데에, 아일랜드로, 중앙을 향하게
- "focal"       : 입구에서 잘 보이게, 정면에, 눈에 띄게, 입구를 향하게
- null          : 명시 없음

## size_modifier 규칙 (resize 액션에만 적용)
- "larger"   : "크게", "더 크게", "키워", "크기 늘려" — 가로+세로 모두 증가
- "smaller"  : "작게", "더 작게", "줄여", "크기 줄여" — 가로+세로 모두 감소
- "wider"    : "넓게", "가로 넓혀", "폭 늘려" — 가로(width)만 증가
- "narrower" : "좁게", "가로 줄여", "폭 줄여" — 가로(width)만 감소
- "taller"   : "높게", "높이 높여", "더 높게" — 높이(height)만 증가
- "shorter"  : "낮게", "높이 낮춰", "더 낮게", "키 줄여" — 높이(height)만 감소
- "max"      : "최대", "가장 크게", "최대 크기로" — 가로+세로 최대
- "min"      : "최소", "가장 작게", "최소 크기로" — 가로+세로 최소
- null       : 명시 없음 (기본 larger 처리)

## scope 규칙 (reorient 액션에만 적용)
- "all"  : "전부", "모두", "전체", "다", 특정 타입 없이 전체 언급
- "type" : 특정 타입만 명시 (기본값)

## wall_hint 규칙 (add 액션에만 적용, 입구에서 안으로 들어갈 때 기준)
- "right"  : 오른쪽 벽, 우측 벽, 오른편, 우측에
- "left"   : 왼쪽 벽, 좌측 벽, 왼편, 좌측에
- "center" : 정면 벽, 맞은편, 입구 맞은편, 가운데 벽
- null     : 벽 위치(좌/우/정면) 언급 없음

## 출력 형식 (JSON만, 설명 없이)
{
  "actions": [
    {
      "action": "add" | "remove" | "resize" | "reorient",
      "object_type": "<코드명 또는 *>",
      "quantity": <숫자 또는 -1>,
      "zone_hint": "<zone 또는 null>",
      "direction_hint": "<direction 또는 null>",
      "size_modifier": "<modifier 또는 null>",
      "scope": "type" | "all",
      "wall_hint": "<right|left|center 또는 null>",
      "original_text": "<원문 조각>"
    }
  ]
}"""

_USER_TEMPLATE = """## 사용자 요구사항
{requirements}

## 현재 배치된 오브젝트 현황 (참고용)
{locked_summary}

## 사용 가능한 배치 포인트 (참고용 — 존/방향 결정에 활용)
{ref_summary}

위 요구사항을 파싱해 actions JSON을 반환하세요."""


# ──────────────────────────────────────────────
# 컨텍스트 빌더
# ──────────────────────────────────────────────

_OBJECT_KO: dict[str, str] = {
    "counter": "계산대",
    "display_table": "진열대",
    "display_table_standard": "진열대(표준형)",
    "character_bbox": "캐릭터 조형물",
    "photo_wall": "포토월",
    "photo_island": "포토 아일랜드",
    "shelf_wall": "벽면 선반",
    "shelf_standard": "표준 선반",
    "shelf_3tier": "3단선반",
    "test_bar": "시연대",
    "consultation_desk": "상담 데스크",
    "banner_stand": "배너",
    "partition_wall_I": "가벽(일자)",
    "partition_wall_L": "가벽(ㄱ자)",
    "signage_stand": "안내판",
    "kiosk": "키오스크",
}


def _build_locked_summary(locked_objects: list[dict]) -> str:
    if not locked_objects:
        return "없음 (최초 배치)"
    lines = []
    for lo in locked_objects:
        obj_type = lo.get("object_type", "unknown")
        name = _OBJECT_KO.get(obj_type, obj_type)
        placed_at = lo.get("anchor_key") or "위치 미상"
        zone = lo.get("zone_label") or ""
        zone_str = f" ({zone})" if zone else ""
        lines.append(f"- {name}: {placed_at}{zone_str}")
    return "\n".join(lines)


def _build_ref_summary(reference_points: list[dict]) -> str:
    """ref_points를 LLM이 존/방향 판단에 활용할 수 있는 형태로 요약."""
    if not reference_points:
        return "없음"

    # zone별로 그룹화해서 보여줌 (전체 목록은 너무 길 수 있으므로 대표만)
    zone_groups: dict[str, list[str]] = {
        "entrance_zone": [],
        "mid_zone": [],
        "deep_zone": [],
        "기타": [],
    }
    for rp in reference_points:
        zone = rp.get("zone_label") or "기타"
        label = rp.get("label") or ""
        wall_normal = rp.get("wall_normal") or ""
        wall_len = rp.get("wall_length_mm") or 0
        rp_id = rp.get("id", "")

        wall_size = ""
        if wall_len > 2000:
            wall_size = "넓은벽"
        elif wall_len > 1000:
            wall_size = "보통벽"
        elif wall_len > 0:
            wall_size = "좁은벽"

        entrance_side = rp.get("entrance_side")
        side_ko = {"right": "입구오른쪽", "left": "입구왼쪽", "center": "입구정면"}.get(entrance_side or "", "")

        desc = rp_id
        parts = [p for p in [side_ko, wall_normal, wall_size, label] if p]
        if parts:
            desc += f" ({', '.join(parts)})"

        target = zone if zone in zone_groups else "기타"
        zone_groups[target].append(desc)

    lines = []
    for zone_name, items in zone_groups.items():
        if items:
            # 너무 많으면 앞 5개만
            shown = items[:5]
            suffix = f" 외 {len(items)-5}개" if len(items) > 5 else ""
            lines.append(f"[{zone_name}] {', '.join(shown)}{suffix}")
    return "\n".join(lines) if lines else "없음"


# ──────────────────────────────────────────────
# LLM 호출
# ──────────────────────────────────────────────

def _call_llm(user_requirements: str, locked_objects: list[dict], reference_points: list[dict]) -> list[dict]:
    """Haiku로 요구사항 파싱 → raw action dict 목록."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise IntentParseError("ANTHROPIC_API_KEY 없음")

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    locked_summary = _build_locked_summary(locked_objects)
    ref_summary = _build_ref_summary(reference_points)

    user_msg = _USER_TEMPLATE.format(
        requirements=user_requirements.strip(),
        locked_summary=locked_summary,
        ref_summary=ref_summary,
    )

    # LLM 설정 중앙 관리 (app.llm_config) — temperature=0 결정론 보장
    from app.llm_config import get_llm_config
    _cfg = get_llm_config("intent_parser")

    try:
        resp = client.messages.create(
            model=_cfg["model"],
            max_tokens=_cfg["max_tokens"],
            temperature=_cfg["temperature"],
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        from app.token_tracker import track_usage
        track_usage("intent_parser.py", resp)
        text = resp.content[0].text.strip()
        # 코드블록 제거
        if "```" in text:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            text = m.group(1) if m else re.sub(r"```[a-z]*", "", text).strip()
        data = json.loads(text)
        return data.get("actions", [])
    except IntentParseError:
        raise
    except Exception as e:
        raise IntentParseError(str(e)) from e


# ──────────────────────────────────────────────
# 검증 / 정규화
# ──────────────────────────────────────────────

_VALID_WALL_HINTS = {"right", "left", "center"}

_VALID_OBJECT_TYPES = {
    "counter", "display_table", "display_table_standard",
    "character_bbox", "photo_wall", "photo_island",
    "shelf_wall", "shelf_standard", "shelf_3tier",
    "test_bar", "consultation_desk",
    "banner_stand", "partition_wall_I", "partition_wall_L",
    "signage_stand", "kiosk",
}
_VALID_ZONES = {"entrance_zone", "mid_zone", "deep_zone"}
_VALID_DIRECTIONS = {"wall_facing", "center", "focal", "inward"}
_VALID_ACTIONS = {"add", "remove", "resize", "reorient"}
_VALID_SIZE_MODIFIERS = {"larger", "smaller", "wider", "narrower", "taller", "shorter", "max", "min"}


def _normalize_action(raw: dict) -> Optional[dict]:
    """raw action dict 검증 및 정규화. 유효하지 않으면 None 반환."""
    action = raw.get("action", "").lower()
    if action not in _VALID_ACTIONS:
        logger.debug(f"[intent_parser] 무효 action: {action}")
        return None

    obj_type = raw.get("object_type", "")
    # reorient scope=all 은 object_type="*" 허용
    if obj_type != "*" and obj_type not in _VALID_OBJECT_TYPES:
        logger.warning(f"[intent_parser] 알 수 없는 object_type: {obj_type!r} — 건너뜀")
        return None

    try:
        quantity = int(raw.get("quantity", 1))
    except (TypeError, ValueError):
        quantity = 1

    zone_hint = raw.get("zone_hint")
    if zone_hint not in _VALID_ZONES:
        zone_hint = None

    direction_hint = raw.get("direction_hint")
    if direction_hint not in _VALID_DIRECTIONS:
        direction_hint = None

    size_modifier = raw.get("size_modifier")
    if size_modifier not in _VALID_SIZE_MODIFIERS:
        size_modifier = "larger" if action == "resize" else None  # resize 기본값은 larger

    scope = raw.get("scope", "type")
    if scope not in ("all", "type"):
        scope = "type"

    wall_hint = raw.get("wall_hint")
    if wall_hint not in _VALID_WALL_HINTS:
        wall_hint = None

    return {
        "action": action,
        "object_type": obj_type,
        "quantity": quantity,
        "zone_hint": zone_hint,
        "direction_hint": direction_hint,
        "size_modifier": size_modifier,
        "scope": scope,
        "wall_hint": wall_hint,
        "original_text": str(raw.get("original_text", "")),
    }


# ──────────────────────────────────────────────
# 퍼블릭 API
# ──────────────────────────────────────────────

def parse_intents(
    user_requirements: str,
    reference_points: list,
    locked_objects: Optional[list] = None,
    # 하위 호환: 기존 코드가 entrance_mm / usable_poly 를 넘기는 경우 무시
    entrance_mm=None,
    usable_poly=None,
) -> list[ResolvedIntent]:
    """
    자연어 요구사항 → ResolvedIntent 목록.

    Parameters
    ----------
    user_requirements : 사용자 입력 텍스트
    reference_points  : ref_point_gen 출력 (zone_label 포함)
    locked_objects    : 현재 배치된 오브젝트 (추가 모드일 때)
    """
    if not user_requirements or not user_requirements.strip():
        return []

    locked = locked_objects or []
    raw_actions = _call_llm(user_requirements, locked, reference_points)
    if not raw_actions:
        return []

    resolved: list[ResolvedIntent] = []
    for raw in raw_actions:
        normalized = _normalize_action(raw)
        if normalized is None:
            continue

        action = normalized["action"]
        is_removal = action == "remove"
        # remove/resize/reorient 는 zone_hint 불필요
        zone_hint = normalized["zone_hint"] if action == "add" else None
        # reorient/add 는 direction_hint 사용, remove/resize 는 불필요
        direction_hint = normalized["direction_hint"] if action in ("add", "reorient") else None

        wall_hint = normalized["wall_hint"] if action == "add" else None
        intent = ResolvedIntent(
            action=action,
            object_type=normalized["object_type"],
            quantity=normalized["quantity"],
            zone_hint=zone_hint,
            direction_hint=direction_hint,
            original_text=normalized["original_text"],
            is_removal=is_removal,
            size_modifier=normalized["size_modifier"],
            scope=normalized["scope"],
            wall_hint=wall_hint,
        )
        resolved.append(intent)
        _action_labels = {"add": "배치", "remove": "제거", "resize": "크기변경", "reorient": "방향전환"}
        action_str = _action_labels.get(action, action)
        logger.info(
            f"[intent_parser] {action_str}: {intent.object_type} ×{intent.quantity}"
            + (f" zone={intent.zone_hint}" if intent.zone_hint else "")
            + (f" dir={intent.direction_hint}" if intent.direction_hint else "")
            + (f" wall={intent.wall_hint}" if intent.wall_hint else "")
            + (f" size={intent.size_modifier}" if intent.size_modifier else "")
            + (f" scope={intent.scope}" if intent.scope != "type" else "")
            + f"  ※\"{intent.original_text}\""
        )

    logger.info(f"[intent_parser] 파싱 완료: {len(resolved)}개 액션")
    return resolved
