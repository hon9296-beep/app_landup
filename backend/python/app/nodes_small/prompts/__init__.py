"""
nodes_small prompt / 검색 키워드 / Tool schema 중앙화 (#491).

흩어진 LLM 호출 입력 (prompt / schema / 키워드) 를 노드별 파일로 분리.
변경 시 prompts/ 만 수정 — 노드 로직 무관.

파일 매핑:
  - ref_image_loader.py — CATEGORY_KEYWORDS / SEARCH_SUFFIX / PINTEREST_FILTER
  - ref_image_analyzer.py — VISION_ANALYSIS_SYSTEM / VISION_ANALYSIS_TOOL / VISION_ANALYSIS_PROMPT
  - reference.py — BRAND_SYSTEM / BRAND_TOOL / BRAND_PROMPT
  - design.py — DESIGN_PROMPT_TEMPLATE
  - design_reviewer.py — LLM_REVIEWER_SYSTEM / build_llm_tool_schema
"""
