/**
 * 프로젝트 플로우 공용 상수
 */
import type { PlacedObject as TPO } from '../../components/ThreeViewer';
import type { LayoutObject } from '../../types/floor';
import type { MarkMode } from '../../context/ProjectContext';

// 오브젝트 타입 정의 — utils.py OBJECT_STANDARDS + nodes_small/reference.py VMD_BOUNDARIES 정식 기준
// (진규 쪽과 통합 가능하도록 백엔드 표준 그대로 따름)

export const OBJECT_NAMES: Record<string, string> = {
  counter: '계산대',
  display_table: '진열대',
  character_bbox: '캐릭터 조형물',
  photo_wall: '포토월',
  photo_island: '포토 아일랜드',
  shelf_wall: '벽면 선반',
  shelf_3tier: '3단 선반',
  banner_stand: '배너',
  partition_wall_I: '가벽(일자형)',
  partition_wall_L: '가벽(ㄱ자형)',
  signage_stand: '안내판',
  kiosk: '키오스크',
  // ── 로컬 테스트용 진열대 기물 ──────────────────────────────────
  folding_chair:  '접이식 의자',
  bar_stool:      '바 스툴',
  office_chair:   '사무용 의자',
  lounge_chair:   '라운지 의자',
  dining_chair:   '다이닝 의자',
  gondola_shelf:     '곤돌라 진열대',
  display_rack_tall: '고형 디스플레이 랙',
  pegboard_stand:    '페그보드 스탠드',
  end_cap_shelf:     '엔드캡 진열대',
  tower_display:     '타워 진열대',
};

export const OBJECT_COLORS: Record<string, string> = {
  counter: '#fde68a',
  display_table: '#bbf7d0',
  character_bbox: '#c4b5fd',
  photo_wall: '#fed7aa',
  photo_island: '#fbbf24',
  shelf_wall: '#bfdbfe',
  shelf_3tier: '#dbeafe',
  banner_stand: '#fef3c7',
  partition_wall_I: '#f1f5f9',
  partition_wall_L: '#cbd5e1',
  signage_stand: '#fecaca',
  kiosk: '#ddd6fe',
  folding_chair:  '#e0f2fe',
  bar_stool:      '#fef3c7',
  office_chair:   '#e2e8f0',
  lounge_chair:   '#fce7f3',
  dining_chair:   '#fef9c3',
  gondola_shelf:     '#99f6e4',
  display_rack_tall: '#5eead4',
  pegboard_stand:    '#2dd4bf',
  end_cap_shelf:     '#14b8a6',
  tower_display:     '#0d9488',
};

// 기본 치수 — VMD_BOUNDARIES.std 값 그대로
export const OBJECT_DEFAULTS: Record<string, { w_mm: number; d_mm: number; h_mm: number }> = {
  counter: { w_mm: 1500, d_mm: 600, h_mm: 900 },
  display_table: { w_mm: 1200, d_mm: 800, h_mm: 850 },
  character_bbox: { w_mm: 600, d_mm: 300, h_mm: 1800 },
  photo_wall: { w_mm: 2400, d_mm: 200, h_mm: 2200 },
  photo_island: { w_mm: 1800, d_mm: 1200, h_mm: 2200 },
  shelf_wall: { w_mm: 1800, d_mm: 400, h_mm: 1800 },
  shelf_3tier: { w_mm: 900, d_mm: 450, h_mm: 1200 },
  banner_stand: { w_mm: 600, d_mm: 400, h_mm: 1800 },
  partition_wall_I: { w_mm: 2000, d_mm: 150, h_mm: 2400 },
  partition_wall_L: { w_mm: 2000, d_mm: 1500, h_mm: 2400 },
  signage_stand: { w_mm: 600, d_mm: 500, h_mm: 900 },
  kiosk: { w_mm: 500, d_mm: 400, h_mm: 1700 },
  folding_chair:  { w_mm: 450, d_mm: 450, h_mm: 880 },
  bar_stool:      { w_mm: 400, d_mm: 400, h_mm: 1050 },
  office_chair:   { w_mm: 650, d_mm: 650, h_mm: 1200 },
  lounge_chair:   { w_mm: 800, d_mm: 800, h_mm: 900 },
  dining_chair:   { w_mm: 450, d_mm: 500, h_mm: 900 },
  gondola_shelf:     { w_mm: 900,  d_mm: 500, h_mm: 1800 },
  display_rack_tall: { w_mm: 1200, d_mm: 600, h_mm: 1800 },
  pegboard_stand:    { w_mm: 900,  d_mm: 400, h_mm: 1800 },
  end_cap_shelf:     { w_mm: 900,  d_mm: 500, h_mm: 1600 },
  tower_display:     { w_mm: 600,  d_mm: 600, h_mm: 2000 },
};

// 로컬 테스트 기물 — DB INSERT 없이 팔레트에 노출. public/models/ 에 GLB 파일 배치 시 폴리곤 렌더링.
export const LOCAL_TEST_FIXTURES: { code: string; nameKo: string; widthStdMm: number; depthStdMm: number; heightStdMm: number }[] = [
  { code: 'folding_chair',  nameKo: '접이식 의자',  widthStdMm: 450, depthStdMm: 450, heightStdMm: 880  },
  { code: 'bar_stool',      nameKo: '바 스툴',      widthStdMm: 400, depthStdMm: 400, heightStdMm: 1050 },
  { code: 'office_chair',   nameKo: '사무용 의자',  widthStdMm: 650, depthStdMm: 650, heightStdMm: 1200 },
  { code: 'lounge_chair',   nameKo: '라운지 의자',  widthStdMm: 800, depthStdMm: 800, heightStdMm: 900  },
  { code: 'dining_chair',   nameKo: '다이닝 의자',  widthStdMm: 450, depthStdMm: 500, heightStdMm: 900  },
  { code: 'gondola_shelf',     nameKo: '곤돌라 진열대',     widthStdMm: 900,  depthStdMm: 500, heightStdMm: 1800 },
  { code: 'display_rack_tall', nameKo: '고형 디스플레이 랙', widthStdMm: 1200, depthStdMm: 600, heightStdMm: 1800 },
  { code: 'pegboard_stand',    nameKo: '페그보드 스탠드',   widthStdMm: 900,  depthStdMm: 400, heightStdMm: 1800 },
  { code: 'end_cap_shelf',     nameKo: '엔드캡 진열대',     widthStdMm: 900,  depthStdMm: 500, heightStdMm: 1600 },
  { code: 'tower_display',     nameKo: '타워 진열대',       widthStdMm: 600,  depthStdMm: 600, heightStdMm: 2000 },
];

export const STATUS_MESSAGES = [
  'Agent가 브랜드 제약 조건을 검토하는 중...',
  'Shapely로 Dead Zone을 계산하는 중...',
  'NetworkX로 보행 거리를 분석하는 중...',
  '오브젝트 배치를 결정하는 중...',
  '배치 검증 및 조정 중...',
];

export const WALL_PRESETS = [
  { label: '1m', length: 1000 },
  { label: '2m', length: 2000 },
  { label: '3m', length: 3000 },
];

/**
 * 이격구역 타입 전수 목록 — 팔레트 팝업에 항상 전체 표시.
 *
 * ⚠️ 규칙 22 중복 매트릭스 (백엔드 DEAD_ZONE_NAMES와 중복) — Shin 2026-04-20 승인 유지.
 * 사유: 백엔드 `spaceData.dead_zones` 는 도면에 실재하는 타입만 담겨옴.
 *       동적 추출 시 도면에 없는 타입(예: 비상구, 기둥) 이 팝업에서 사라져 UX 깨짐.
 *       팝업은 "항상 전체 토글 옵션 표시" 해야 사용자가 켜고 끌 수 있음.
 * 동기화: 백엔드 vmd_constants.DEAD_ZONE_NAMES 변경 시 이 배열도 수동 갱신.
 *
 * ⚠️ 원래 ResultPalette.tsx 에 있었으나, 컴포넌트 파일에서 값 export 하면 Vite React
 *    Fast Refresh 가 바로 HMR 포기함 (컴포넌트 + 상수 혼합 export 금지). 2026-04-23 이동.
 */
export const DEAD_ZONE_TYPES: { value: string; label: string }[] = [
  { value: 'sprinkler', label: '스프링클러' },
  { value: 'fire_hydrant', label: '소화전' },
  { value: 'electrical_panel', label: '분전반' },
  { value: 'emergency_exit', label: '비상구' },
  { value: 'inner_wall', label: '내벽' },
  { value: 'core', label: '화장실/계단' },
  { value: 'toilet', label: '화장실' },
  { value: 'stair', label: '계단' },
  { value: 'pillar', label: '기둥' },
  { value: 'core_access', label: '진입로 확보' },
  { value: 'unknown', label: '기타' },
];

export const MODE_CFG: Record<Exclude<MarkMode, null>, { label: string; activeClass: string }> = {
  entrance: { label: '입구', activeClass: 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300' },
  sprinkler: { label: '스프링클러', activeClass: 'bg-blue-500/20 border-blue-500/50 text-blue-300' },
  fire_hydrant: { label: '소화전', activeClass: 'bg-orange-500/20 border-orange-500/50 text-orange-300' },
  electrical_panel: { label: '분전반', activeClass: 'bg-purple-500/20 border-purple-500/50 text-purple-300' },
  // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
  // scale_anchor: { label: '스케일 앵커', activeClass: 'bg-yellow-500/20 border-yellow-500/50 text-yellow-300' },
};

let wallIdCounter = 0;
export const newWallId = () => `wall_${++wallIdCounter}`;

// ── 면적 유틸 ──────────────────────────────────────────────
// 백엔드 기준과 일치: SCALE_THRESHOLD_M2 = 165㎡ = 50평
// 50평 이하 = 소형·중형 (진규 영역, venue_type·density 적용)
// 50평 초과 = 대형 (shin 영역, 자동)
const SMALL_THRESHOLD_MM2 = 165_000_000; // 165㎡
const MM2_PER_PYEONG = 3_305_785; // 1평 ≈ 3.3058㎡

/** 폴리곤(px) + 스케일(mm/px)로 면적(mm²) 계산 — Shoelace */
export function calcAreaMm2(polygonPx: number[][], scaleMmPerPx: number): number {
  if (!polygonPx || polygonPx.length < 3) return 0;
  const s = scaleMmPerPx || 1;
  let area = 0;
  for (let i = 0; i < polygonPx.length; i++) {
    const j = (i + 1) % polygonPx.length;
    area += (polygonPx[i][0] * s) * (polygonPx[j][1] * s);
    area -= (polygonPx[j][0] * s) * (polygonPx[i][1] * s);
  }
  return Math.abs(area) / 2;
}

/** 폴리곤(mm)으로 직접 면적(mm²) 계산 — spaceData.floor.polygon_mm 용 */
export function calcAreaMm2FromMm(polygonMm: number[][]): number {
  if (!polygonMm || polygonMm.length < 3) return 0;
  let area = 0;
  for (let i = 0; i < polygonMm.length; i++) {
    const j = (i + 1) % polygonMm.length;
    area += polygonMm[i][0] * polygonMm[j][1];
    area -= polygonMm[j][0] * polygonMm[i][1];
  }
  return Math.abs(area) / 2;
}

/** "48.3㎡ (14.6평)" 포맷 */
export function formatArea(mm2: number): string {
  const m2 = mm2 / 1_000_000;
  const pyeong = mm2 / MM2_PER_PYEONG;
  return `${m2.toFixed(1)}㎡ (${pyeong.toFixed(1)}평)`;
}

/** 소형·중형(≤50평) 여부 */
export function isSmallScale(mm2: number): boolean {
  return mm2 > 0 && mm2 <= SMALL_THRESHOLD_MM2;
}

export function toLO(obj: LayoutObject): TPO {
  return {
    object_type: obj.object_type,
    position_mm: [obj.center_x_mm, obj.center_y_mm],
    rotation_deg: obj.rotation_deg ?? 0,
    bbox_mm: [obj.width_mm, obj.depth_mm],
    height_mm: obj.height_mm ?? 1500,
    reference_point: obj.anchor_key ?? '',
    placed_because: obj.placed_because ?? '',
  };
}
