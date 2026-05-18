"""
ref 이미지 영향 검증 CLI — A/B/Counterfactual 비교.

사용:
    python -m scripts.validate_ref \
        --space-data path/to/space_data_full.json \
        --brand-category 뷰티·코스메틱 \
        [--counterfactual character_ip] \
        [--out validation_report.md]

3 가지 모드:
  A (baseline) : 정상 — analyzer 결과 그대로 design 에 주입
  B (disabled) : REF_DISABLE=1 — ref_analysis 무시, LLM 호출은 진행 (룰만 적용)
  C (swap)     : REF_FIXTURE_CATEGORY=<other> — 다른 카테고리 ref_analysis 강제 주입

비교 metric: app.metrics.placement_distance.compare_placements
출력: 콘솔 표 + (옵션) markdown 보고서

주의:
  - 각 모드마다 LLM 호출 발생 (Anthropic API key 필요).
  - 비용 1회당 약 $0.05 ~ $0.10. 3회 = 약 $0.30.
  - 같은 도면을 3번 돌리므로 시간 1~3분 소요.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# project_root/backend/python 을 path 에 추가 (scripts/ 직접 실행 호환)
_THIS = Path(__file__).resolve()
_PYTHON_ROOT = _THIS.parents[1]
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from app.metrics.placement_distance import compare_placements, PlacementMetric  # noqa: E402
from app.services.ref_analysis_fixture import list_available_categories          # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("validate_ref")


def _load_space_data(path: str) -> dict:
    """space_data_full.json → /place body 형식."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    body = {
        "floor":           raw.get("floor", {}),
        "entrance":        raw.get("entrance", {}),
        "brand_dict":      raw.get("brand", {}),
        "brand_category":  None,   # CLI 인자가 override 함
        "dead_zones":      raw.get("dead_zones", []),
        "sprinklers_mm":   raw.get("sprinklers_mm", []),
        "hydrants_mm":     raw.get("hydrants_mm", []),
        "electric_panels_mm": raw.get("electric_panels_mm", []),
    }
    return body


def _run_mode(body: dict, brand_category: str, mode: str, counterfactual_slug: Optional[str] = None) -> dict:
    """단일 모드 실행 → {"placed_objects": [...], "design_fallback_reason": ...} 반환.

    각 모드별 환경변수 설정:
      A: 둘 다 unset
      B: REF_DISABLE=1
      C: REF_FIXTURE_CATEGORY=<slug>
    """
    # env 초기화 (이전 모드 잔재 방지)
    os.environ.pop("REF_DISABLE", None)
    os.environ.pop("REF_FIXTURE_CATEGORY", None)

    if mode == "B":
        os.environ["REF_DISABLE"] = "1"
    elif mode == "C":
        if not counterfactual_slug:
            raise ValueError("mode C 는 counterfactual_slug 필요")
        os.environ["REF_FIXTURE_CATEGORY"] = counterfactual_slug

    # state 빌드 + place_small 호출
    body_copy = dict(body)
    body_copy["brand_category"] = brand_category

    from app.services.state_builder import rebuild_state_from_body
    from app.services.place_service import place_small

    state = rebuild_state_from_body(body_copy)
    logger.info(f"[mode {mode}] state rebuilt — usable_poly area: "
                f"{state.get('usable_poly').area / 1_000_000:.1f}㎡" if state.get("usable_poly") else "[mode] no usable_poly")

    result = place_small(state)
    # format_place_response 의 return key 는 'objects' (placed_objects 아님). debug dump 와 다름.
    placed = (result.get("objects") or []) if result else []
    fallback_reason = state.get("design_fallback_reason")
    logger.info(f"[mode {mode}] placed: {len(placed)}, fallback_reason: {fallback_reason}")
    return {"placed_objects": placed, "design_fallback_reason": fallback_reason, "mode": mode}


def _format_metric(label: str, m: PlacementMetric) -> str:
    s = m.summary()
    sig = "✅ 차이 있음" if m.is_significantly_different() else "❌ 차이 없음"
    return (
        f"\n=== {label} ===\n"
        f"  객체 수: A={s['n_a']}, B={s['n_b']}, 매칭={s['matched_pairs']}\n"
        f"  type_match_rate: {s['type_match_rate']:.0%}\n"
        f"  unmatched_A (B에 없음): {s['unmatched_a']}\n"
        f"  unmatched_B (A에 없음): {s['unmatched_b']}\n"
        f"  좌표 거리 (mm): mean={s['centroid_distance_mm']['mean']:.0f}, "
        f"median={s['centroid_distance_mm']['median']:.0f}, max={s['centroid_distance_mm']['max']:.0f}\n"
        f"  회전 차 (deg):   mean={s['rotation_diff_deg']['mean']:.1f}, "
        f"median={s['rotation_diff_deg']['median']:.1f}, max={s['rotation_diff_deg']['max']:.1f}\n"
        f"  판정: {sig}"
    )


def _markdown_report(brand_category: str, results: dict, m_ab: PlacementMetric, m_ac: Optional[PlacementMetric]) -> str:
    lines = [
        "# ref 이미지 영향 검증 보고서",
        "",
        f"카테고리: **{brand_category}**",
        f"시점: {os.popen('date +\"%Y-%m-%d %H:%M\"').read().strip() if os.name != 'nt' else ''}",
        "",
        "## 모드별 결과",
        "",
        f"- A (baseline): {len(results['A']['placed_objects'])} 객체, fallback={results['A']['design_fallback_reason']}",
        f"- B (REF_DISABLE): {len(results['B']['placed_objects'])} 객체, fallback={results['B']['design_fallback_reason']}",
    ]
    if m_ac is not None:
        lines.append(f"- C (counterfactual): {len(results['C']['placed_objects'])} 객체, fallback={results['C']['design_fallback_reason']}")

    lines.extend(["", "## A vs B (ref 정상 vs ref 무시)", "```", _format_metric("A vs B", m_ab).strip(), "```"])
    if m_ac is not None:
        lines.extend(["", "## A vs C (ref 정상 vs counterfactual swap)", "```", _format_metric("A vs C", m_ac).strip(), "```"])

    lines.extend([
        "",
        "## 해석 가이드",
        "",
        "- **A vs B 차이 있음** = ref 이미지가 design 결과에 실효 영향을 줌 (ref 시스템 작동 증거)",
        "- **A vs B 차이 없음** = ref 무시해도 같은 결과 → ref 이미지가 사실상 무영향",
        "- **A vs C 차이 큼** = 다른 카테고리 ref 주입 시 결과가 그 방향으로 흔들림 (강한 영향력 증거)",
        "- **A vs C 차이 작음** = ref 가 카테고리에 무관하게 비슷한 결과 → ref 영향 약함",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-data", required=True, help="space_data_full.json 경로")
    parser.add_argument("--brand-category", required=True, help="예: 뷰티·코스메틱")
    parser.add_argument("--counterfactual", default=None,
                        help=f"counterfactual swap 카테고리 (옵션). 사용 가능: {list_available_categories()}")
    parser.add_argument("--out", default=None, help="markdown 보고서 출력 경로 (옵션)")
    args = parser.parse_args()

    body = _load_space_data(args.space_data)

    results = {}
    logger.info("== mode A (baseline — ref 정상) ==")
    results["A"] = _run_mode(body, args.brand_category, "A")

    logger.info("== mode B (REF_DISABLE — ref 무시) ==")
    results["B"] = _run_mode(body, args.brand_category, "B")

    if args.counterfactual:
        logger.info(f"== mode C (counterfactual swap → {args.counterfactual}) ==")
        results["C"] = _run_mode(body, args.brand_category, "C", counterfactual_slug=args.counterfactual)

    # 비교
    m_ab = compare_placements(results["A"]["placed_objects"], results["B"]["placed_objects"])
    print(_format_metric("A (baseline) vs B (REF_DISABLE)", m_ab))

    m_ac = None
    if args.counterfactual:
        m_ac = compare_placements(results["A"]["placed_objects"], results["C"]["placed_objects"])
        print(_format_metric(f"A (baseline) vs C (swap → {args.counterfactual})", m_ac))

    if args.out:
        report = _markdown_report(args.brand_category, results, m_ab, m_ac)
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n[report] 저장: {args.out}")


if __name__ == "__main__":
    main()
