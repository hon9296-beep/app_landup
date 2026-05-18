/**
 * AnalysisReport mock fixture — 2026-04-23 11:03 fashion LUMIA 실측 케이스 기반.
 *
 * Schema 는 backend/python/debug_logs/YYYY-MM-DD/ 의 실제 JSON 구조에 근접하도록 구성.
 * 추후 Python `/api/report/latest` endpoint 붙일 때 endpoint 스펙 이 타입에 맞춰서
 * 구현하면 migration 이 1줄 교체로 끝남.
 *
 * 소스 JSON 매핑:
 *   summary       ← object_selection_debug.json + token_usage.json + dead_zones_detail.json
 *   placements    ← place_result.json + brand_data.pair_rules
 *   fireRegulation← brand_data.fire
 *   pathCriteria  ← space_data_full.json (main_artery, zone_map)
 *   deadZones     ← dead_zones_detail.json
 *   clearance     ← brand_data.construction + placement_rules[].clearance
 *   vmdRules      ← brand_data.pair_rules
 *   referenceImages ← ref_trace.json
 */

export type PairRelation = 'adjacent' | 'join' | 'separate';
export type RefSource = 'local_cache' | 'ddg_pinterest' | 'empty';
export type DeadZoneType = 'pillar' | 'toilet' | 'stair' | 'core';

export interface PlacementLinkedRule {
  target: string; // object_type
  targetName: string; // 한글명
  relation: PairRelation;
  minGapMm: number;
}

export interface PlacementEntry {
  rank: number;
  objectType: string;
  name: string;
  placedBecause: string;
  linkedRules: PlacementLinkedRule[];
}

export interface InputSummary {
  floor: {
    areaMm2: number;
    areaM2: number;
    ceilingHeightMm: number;
    entranceCount: number;
    sprinklerCount: number;
    deadZoneCount: number;
  };
  brand: {
    category: string;
    clearspaceMm: number | null;
    prohibitedMaterial: string | null;
    hasBrandManual: boolean;
  };
  hasCrossSection: boolean;
}

export interface AnalysisReportData {
  // 사용자 입력 요약 (도면 + 브랜드 매뉴얼)
  inputSummary?: InputSummary;

  // Phase 1 — Overview
  summary: {
    placedCount: number;
    eligibleCount: number;
    ruleCount: number;
    deadZoneCount: number;
    tokensInput: number;
    tokensOutput: number;
    costUsd: number;
    durationSec: number;
  };

  // Phase 2 — 타임라인 (항목 1 배치 사유 + 항목 8 근접 로직)
  placements: PlacementEntry[];

  // Phase 3 — 제약 & 환경
  fireRegulation: {
    mainCorridorMinMm: number;
    emergencyPathMinMm: number;
  };
  pathCriteria: {
    mainArteryDescription: string;
    zones: Array<{ key: string; label: string }>;
    subPathSupported: boolean; // 현재 항상 false — 추후 지원
  };
  deadZones: Array<{ type: DeadZoneType; label: string }>;
  clearance: {
    wallClearanceMm: number;
    objectGapMm: number;
  };
  vmdRules: Array<{
    objectA: string;
    objectAName: string;   // 한글 표시명 — UI 렌더 전용
    objectB: string;
    objectBName: string;
    relation: PairRelation;
    minGapMm: number;
    source?: 'vmd_default' | 'manual';   // UI 에서는 "시스템 기본" / "매뉴얼 지정" 으로 치환
  }>;
  referenceImages: {
    category: string;
    source: RefSource;
    count: number;
  };

  // Phase 3-7: 배치 순위 결정 기준 (backend allocator sort logic 투명 공개)
  prioritySort: {
    formula: string;
    factors: Array<{
      label: string;
      value?: string;         // 예: "+20" / "+1000"
      description: string;
    }>;
  };
}

// ── Mock fixture (LUMIA 18평 패션 브랜드 케이스) ────────────────────────

export const MOCK_ANALYSIS_REPORT: AnalysisReportData = {
  inputSummary: {
    floor: {
      areaMm2: 59_504_400,
      areaM2: 59.5,
      ceilingHeightMm: 2800,
      entranceCount: 1,
      sprinklerCount: 4,
      deadZoneCount: 3,
    },
    brand: {
      category: '패션·의류',
      clearspaceMm: 300,
      prohibitedMaterial: null,
      hasBrandManual: true,
    },
    hasCrossSection: true,
  },
  summary: {
    placedCount: 8,
    eligibleCount: 9,
    ruleCount: 19,
    deadZoneCount: 3,
    tokensInput: 11990,
    tokensOutput: 4619,
    costUsd: 0.1192,
    durationSec: 42,
  },

  placements: [
    {
      rank: 1,
      objectType: 'partition_wall_I',
      name: '가벽(일자형)',
      placedBecause:
        '공간 분할 및 룩북 가벽 활용을 위해 좌측 벽면 mid_zone 구간에 최우선 배치.',
      linkedRules: [
        { target: 'photo_wall', targetName: '포토월', relation: 'join', minGapMm: 0 },
        { target: 'shelf_wall', targetName: '벽면 선반', relation: 'join', minGapMm: 0 },
      ],
    },
    {
      rank: 2,
      objectType: 'photo_wall',
      name: '포토월',
      placedBecause:
        '메인 앵커 기물로서 선행 배치된 파티션에 결합하여 동선 끝단에 포토존 형성.',
      linkedRules: [
        { target: 'partition_wall_I', targetName: '가벽(일자형)', relation: 'join', minGapMm: 0 },
      ],
    },
    {
      rank: 3,
      objectType: 'counter',
      name: 'POS 카운터',
      placedBecause:
        '결제 대기열 확보를 위해 출입구 직선 궤적을 피해 deep_zone 측면 벽으로 전진 배치.',
      linkedRules: [
        { target: '*', targetName: '타 기물 전체', relation: 'separate', minGapMm: 1200 },
      ],
    },
    {
      rank: 4,
      objectType: 'fitting_room',
      name: '피팅룸',
      placedBecause:
        '매뉴얼 명시 deep_zone 깊은 벽면에 배치. 입구 정면 노출 회피.',
      linkedRules: [
        { target: 'fitting_room', targetName: '피팅룸', relation: 'adjacent', minGapMm: 100 },
      ],
    },
    {
      rank: 5,
      objectType: 'display_table',
      name: '센터 아일랜드 테이블',
      placedBecause:
        '매뉴얼 지정 mid_zone 중앙에 센터 아일랜드로 배치. 신제품 노출 우선.',
      linkedRules: [
        { target: 'display_table', targetName: '진열대', relation: 'separate', minGapMm: 600 },
      ],
    },
    {
      rank: 6,
      objectType: 'aux_table',
      name: '포장 보조 테이블',
      placedBecause: '결제 후 룩북 포장을 위해 counter 근접 배치.',
      linkedRules: [],
    },
    {
      rank: 7,
      objectType: 'signage_stand',
      name: '룩북 스탠드(이젤형)',
      placedBecause: 'entrance_zone 에 브랜드 소개 룩북 노출용 스탠드 배치.',
      linkedRules: [],
    },
    {
      rank: 8,
      objectType: 'shelf_3tier',
      name: '3단 선반',
      placedBecause: '벽면 보조 진열로 side_wall 에 배치.',
      linkedRules: [],
    },
  ],

  fireRegulation: {
    mainCorridorMinMm: 900,
    emergencyPathMinMm: 1200,
  },

  pathCriteria: {
    mainArteryDescription: '입구 → mid_zone → deep_zone 관통 주동선 생성.',
    zones: [
      { key: 'entrance_zone', label: 'Entrance · 감압 및 후킹 구역' },
      { key: 'mid_zone', label: 'Mid · 핵심 제품 관여 및 순환 구역' },
      { key: 'deep_zone', label: 'Deep · 목적지 및 백오피스 구역' },
    ],
    subPathSupported: false,
  },

  deadZones: [
    { type: 'pillar', label: '중앙 기둥 1곳' },
    { type: 'core', label: '좌측 코어 접근선 1곳' },
    { type: 'toilet', label: '화장실 인접 벽 1곳' },
  ],

  clearance: {
    wallClearanceMm: 300,
    objectGapMm: 300,
  },

  vmdRules: [
    { objectA: 'partition_wall_I', objectAName: '가벽(일자형)', objectB: 'photo_wall',       objectBName: '포토월',          relation: 'join',     minGapMm: 0,    source: 'vmd_default' },
    { objectA: 'partition_wall_I', objectAName: '가벽(일자형)', objectB: 'shelf_wall',       objectBName: '벽면 선반',       relation: 'join',     minGapMm: 0,    source: 'vmd_default' },
    { objectA: 'partition_wall_I', objectAName: '가벽(일자형)', objectB: 'shelf_3tier',      objectBName: '3단 선반',        relation: 'join',     minGapMm: 0,    source: 'vmd_default' },
    { objectA: 'partition_wall_I', objectAName: '가벽(일자형)', objectB: '*',                objectBName: '모든 기물',       relation: 'separate', minGapMm: 600,  source: 'vmd_default' },
    { objectA: 'partition_wall_I', objectAName: '가벽(일자형)', objectB: 'partition_wall_I', objectBName: '가벽(일자형)',    relation: 'separate', minGapMm: 1200, source: 'vmd_default' },
    { objectA: 'counter',          objectAName: '계산대',       objectB: '*',                objectBName: '모든 기물',       relation: 'separate', minGapMm: 1200, source: 'vmd_default' },
    { objectA: 'display_table',    objectAName: '진열대',       objectB: 'display_table',    objectBName: '진열대',          relation: 'separate', minGapMm: 600,  source: 'vmd_default' },
    { objectA: 'shelf_wall',       objectAName: '벽면 선반',    objectB: 'shelf_wall',       objectBName: '벽면 선반',       relation: 'join',     minGapMm: 0,    source: 'vmd_default' },
    { objectA: 'fitting_room',     objectAName: '피팅룸',       objectB: 'fitting_room',     objectBName: '피팅룸',          relation: 'adjacent', minGapMm: 100,  source: 'manual' },
    { objectA: 'mannequin',        objectAName: '마네킹',       objectB: 'mannequin',        objectBName: '마네킹',          relation: 'separate', minGapMm: 800,  source: 'manual' },
    { objectA: 'mannequin',        objectAName: '마네킹',       objectB: 'photo_wall',       objectBName: '포토월',          relation: 'separate', minGapMm: 600,  source: 'manual' },
  ],

  referenceImages: {
    category: '뷰티·코스메틱',
    source: 'local_cache',
    count: 4,
  },

  prioritySort: {
    formula: '각 기물에 점수를 매긴 뒤, 점수가 높은 순으로 먼저 배치합니다. 점수가 같으면 작은 기물이 먼저 자리를 잡습니다.',
    factors: [
      {
        label: '기물 기본 중요도',
        description:
          '기물마다 매장 내 역할에 따라 기본 점수가 정해져 있습니다. 공간을 나누는 가벽이나 브랜드 카운터처럼 핵심 역할 기물은 높은 기본 점수를, 안내판·배너처럼 보조 기물은 낮은 점수를 받습니다.',
      },
      {
        label: '브랜드 매뉴얼 반영',
        value: '+20점',
        description:
          '브랜드 매뉴얼에서 "꼭 배치해달라"고 명시한 기물은 추가 점수를 받아 우선적으로 자리를 확보합니다.',
      },
      {
        label: '공간 구조 앵커 보너스',
        value: '+1000점',
        description:
          '가벽·포토존처럼 매장의 뼈대를 이루는 기물은 다른 기물 배치의 기준점이 되므로 압도적으로 높은 점수를 받아 가장 먼저 배치됩니다.',
      },
      {
        label: '같은 종류 기물 개수 제한',
        description:
          '선반 계열, 진열대 계열 등 비슷한 용도의 기물이 한 공간에 몰리지 않도록 종류별 최대 개수를 제한합니다.',
      },
      {
        label: '동점일 땐 작은 기물 우선',
        description:
          '두 기물의 점수가 같다면, 공간을 덜 차지하는 기물을 먼저 배치해 전체 공간 효율을 확보합니다.',
      },
    ],
  },
};
