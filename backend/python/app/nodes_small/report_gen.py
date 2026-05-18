"""
배치 리포트 생성 노드 — rendy/modules/report_generator.py 기반.

배치 결과 + 검증 결과 → 디자이너 리뷰용 텍스트 리포트.
f-string 템플릿, LLM 없음.
"""
import logging
from datetime import datetime

from app.state import SmallState

logger = logging.getLogger(__name__)


def run(state: SmallState) -> SmallState:
    """배치 결과 리포트 생성."""
    placed = state.get("placed_objects") or []
    failed = state.get("failed_objects") or []
    verification = state.get("verification") or {}
    brand_data = state.get("brand_data") or {}
    usable_poly = state.get("usable_poly")
    fallback_round = state.get("fallback_round", 0)

    lines = []

    # 헤더
    lines.append("=" * 60)
    lines.append("LandingUp 배치 기획 리포트")
    lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 60)
    lines.append("")

    # 공간 요약
    lines.append("## 공간 요약")
    if usable_poly:
        lines.append(f"- 가용 면적: {usable_poly.area / 1_000_000:.1f}m2")
    zone_map = state.get("zone_map") or {}
    if zone_map:
        lines.append(f"- zone 분포: {zone_map}")
    lines.append("")

    # 브랜드 제약 요약
    brand = brand_data.get("brand", {})
    lines.append("## 브랜드 제약")
    for key in ["clearspace_mm", "logo_clearspace_mm", "character_orientation", "prohibited_material"]:
        field = brand.get(key, {})
        if isinstance(field, dict) and field.get("value") is not None:
            lines.append(f"- {key}: {field['value']} "
                         f"({field.get('confidence', '?')} / {field.get('source', '?')})")
    lines.append("")

    # 배치 결과
    lines.append(f"## 배치 결과 ({len(placed)}개 배치, {len(failed)}개 실패)")
    lines.append("")

    for i, p in enumerate(placed, 1):
        lines.append(f"### {i}. {p.get('object_type', '?')}")
        lines.append(f"- 위치: ({p.get('center_x_mm', '?')}, {p.get('center_y_mm', '?')})mm")
        lines.append(f"- 회전: {p.get('rotation_deg', 0)}deg")
        lines.append(f"- 크기: {p.get('width_mm', '?')}x{p.get('depth_mm', '?')}mm")
        lines.append(f"- anchor: {p.get('anchor_key', '?')}")
        lines.append(f"- zone: {p.get('zone_label', '?')}")
        lines.append(f"- direction: {p.get('direction', '?')}")
        lines.append(f"- 배치 근거: {p.get('placed_because', '?')}")
        lines.append("")

    # 실패 항목
    if failed:
        lines.append("## 실패 오브젝트")
        for d in failed:
            lines.append(f"- {d.get('object_type', '?')}: {d.get('reason', '?')}")
        lines.append("")

    # 검증 결과
    lines.append("## 검증 결과")
    lines.append(f"- 판정: {'PASS' if verification.get('passed') else 'FAIL'}")
    for b in verification.get("blocking", []):
        lines.append(f"- [BLOCKING] {b['object_type']}: {b['detail']}")
    for w in verification.get("warning", []):
        lines.append(f"- [WARNING] {w['object_type']}: {w['detail']}")
    lines.append("")

    # fallback 표기
    if fallback_round > 0:
        lines.append("## 주의사항")
        lines.append(f"- Fallback {fallback_round}회 실행됨.")
        lines.append("- 디자이너 검토 후 위치 조정을 권장합니다.")
        lines.append("")

    # disclaimer
    lines.append("---")
    lines.append("본 리포트는 AI가 자동 생성한 초안입니다.")
    lines.append("소방 통로 규정(900mm/1200mm)은 관할 소방서 기준을 우선 적용하세요.")

    report = "\n".join(lines)
    logger.info(f"[report_gen] {len(lines)} lines generated")

    return {"report_text": report}
