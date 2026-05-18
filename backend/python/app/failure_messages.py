"""
배치 실패 사유 ↔ 사용자 친화 메시지 매핑.

기술적 실패 reason 문자열(placement/verify 노드에서 뱉음)을
프론트가 그대로 보여줄 수 있는 한국어 설명으로 번역.
"""

# object_type → 한국어 이름
OBJECT_KO: dict[str, str] = {
    "counter": "계산대",
    "display_table": "진열대",
    "character_bbox": "캐릭터 조형물",
    "photo_wall": "포토월",
    "photo_island": "포토 아일랜드",
    "shelf_wall": "벽면 선반",
    "shelf_3tier": "3단선반",
    "banner_stand": "배너",
    "partition_wall_I": "가벽",
    "signage_stand": "안내판",
    "kiosk": "키오스크",
}

# reason 키워드 → 사람 읽는 설명 (순서대로 매칭, 먼저 히트한 게 채택)
FAILURE_REASON_EXPLAINS: list[tuple[str, str]] = [
    ("density limit",   "공간 밀도 제한 초과 — 매장이 이미 충분히 채워져 있어 추가 배치가 어렵습니다"),
    ("floor_overlap",   "배치 공간 부족 — 주변 오브젝트나 벽이 있어 들어갈 자리가 없습니다"),
    ("VMD R4 위반",     "입구존 높이 제한 — 입구 근처에는 가슴 높이(1200mm) 이하 오브젝트만 배치 가능합니다"),
    ("VMD R2 위반",     "계산대 위치 제한 — 계산대는 매장 안쪽(mid/deep zone)에만 배치 가능합니다"),
    ("VMD 무관용 차단", "VMD 규칙 위반 — 브랜드 가이드라인에 의해 해당 위치에 배치할 수 없습니다"),
    ("sprinkler",       "높이 제한 — 오브젝트가 너무 높아 스프링클러 헤드를 가립니다. 높이를 낮추거나 다른 위치에 배치하세요"),
    ("choke",           "통로 차단 — 배치 시 이동 통로가 900mm 미만으로 좁아져 배치할 수 없습니다"),
    ("center 상한",     "중앙 배치 제한 — 소형 매장에서 중앙 배치는 최대 2개로 제한됩니다"),
    ("eligible에 없음", "오브젝트 없음 — 브랜드 목록에 없거나 이미 최대 수량이 배치되었습니다"),
]
