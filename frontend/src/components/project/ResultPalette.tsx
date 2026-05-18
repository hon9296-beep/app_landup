/**
 * ResultPalette — 결과 편집 플로팅 팔레트 (포토샵 스타일)
 *
 * 세로 3열, 3행 격자 배치. 헤더 드래그로 위치 이동.
 * 이격/가벽/추가 버튼은 팝오버로 세부 선택.
 */
import { useEffect, useRef, useState } from 'react';
import { GripHorizontal, X } from 'lucide-react';  // 팝업 헤더 전용 (팔레트 본 버튼엔 미사용)
import { WALL_PRESETS, OBJECT_NAMES, OBJECT_COLORS, LOCAL_TEST_FIXTURES } from '../../pages/project/_constants';
import type { ObjectPaletteItem } from '../../lib/api';

// ════════════════════════════════════════════════════════════════
// PaletteIcon — 팔레트 버튼 전용 통합 아이콘 컴포넌트
// ════════════════════════════════════════════════════════════════
//
// 왜 통합했나:
//   - lucide 아이콘들은 24×24 viewBox 안에서 실제 path bbox 가 제각각 (8×20 ~ 20×20).
//     같은 size 로 렌더링해도 시각 크기가 2.5배까지 차이남.
//   - 아이콘마다 size prop 개별 조정하거나 strokeWidth 로 보정하려 했으나
//     근본적 해결 안 됨 → 아예 전부 직접 그려 bbox 를 내가 통제.
//
// 공통 규격:
//   - viewBox "0 0 24 24"
//   - strokeWidth 2, linecap/linejoin round
//   - 모든 path 가 bbox 2~22 (= 20×20, viewBox 의 83%) 을 최대한 채움
//   - size 기본 18
//
// rotate-90 이 필요한 'flow' (동선 buffer 모드) 만 className 전달 허용.
//
// ⚠️ 새 팔레트 아이콘 추가 시: 이 파일 안에서 PaletteIconName 과 switch 에만 추가.
//     다른 곳에서 lucide 개별 import 하거나 별도 SVG 쓰면 또 불균형 생김.

export type PaletteIconName =
  | 'view' | 'move' | 'rotate'
  | 'copy' | 'dead-zone' | 'wall-toggle'
  | 'partition' | 'flow' | 'plus' | 'trash';

function PaletteIcon({
  name, size = 18, className,
}: {
  name: PaletteIconName;
  size?: number;
  className?: string;
}) {
  const svgProps = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
  };

  // 공통 외곽 프레임 — 모든 아이콘에 동일하게 깔아 "시각 영역" 강제 통일.
  // 열린 도형(plus/화살표)과 닫힌 도형(rect/circle) 간 게슈탈트 지각 차이를
  // bbox 수치로는 못 맞추기에, 프레임으로 우회.
  // wall-toggle / partition 은 자체 외곽 사각이라 중복 프레임 생략 (분기 처리).
  const Frame = () => (
    <rect
      x="2" y="2" width="20" height="20" rx="2"
      strokeOpacity="0.12"
    />
  );

  switch (name) {
    // ── 1행 ──────────────────────────────────────────────────
    case 'view':     // 눈 (보기) — 렌즈형
      return (
        <svg {...svgProps}>
          <Frame />
          <path d="M2 12C5 4 8 2 12 2s7 2 10 10c-3 8-6 10-10 10s-7-2-10-10Z" />
          <circle cx="12" cy="12" r="3.5" />
        </svg>
      );
    case 'move':     // 4방향 화살표 (이동)
      return (
        <svg {...svgProps}>
          <Frame />
          <path d="M12 2v20" />
          <path d="M2 12h20" />
          <path d="m9 5 3-3 3 3" />
          <path d="m9 19 3 3 3-3" />
          <path d="m5 9-3 3 3 3" />
          <path d="m19 9 3 3-3 3" />
        </svg>
      );
    case 'rotate':   // 시계 방향 회전 화살표
      return (
        <svg {...svgProps}>
          <Frame />
          <path d="M22 12a10 10 0 1 1-10-10c2.8 0 5.5 1.1 7.5 3L22 7" />
          <path d="M22 2v5h-5" />
        </svg>
      );

    // ── 2행 ──────────────────────────────────────────────────
    case 'copy':     // 겹친 두 사각형 (복사)
      return (
        <svg {...svgProps}>
          <Frame />
          <rect x="8" y="8" width="14" height="14" rx="2" />
          <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
        </svg>
      );
    case 'dead-zone': // 원 + 느낌표 (이격구역 경고)
      return (
        <svg {...svgProps}>
          <Frame />
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="7" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      );
    case 'wall-toggle': // 자체 외곽 rect — Frame 생략
      return (
        <svg {...svgProps}>
          <rect x="2" y="2" width="20" height="20" rx="2" />
        </svg>
      );

    // ── 3행 ──────────────────────────────────────────────────
    case 'partition': // 자체 외곽 rect — Frame 생략
      return (
        <svg {...svgProps}>
          <rect x="2" y="2" width="20" height="20" rx="2" />
          <line x1="12" y1="2" x2="12" y2="22" />
        </svg>
      );
    case 'flow':     // 동선 화살표 (buffer 모드 rotate-90)
      return (
        <svg {...svgProps}>
          <Frame />
          <path d="M12 22V2" />
          <path d="M2 12l10-10 10 10" />
        </svg>
      );
    case 'plus':     // 추가 십자
      return (
        <svg {...svgProps}>
          <path d="M12 2v20" />
          <path d="M2 12h20" />
        </svg>
      );
    case 'trash':    // 휴지통 (삭제)
      return (
        <svg {...svgProps}>
          <Frame />
          <path d="M4 8h16" />
          <path d="M10 8V5h4v3" />
          <path d="M6 8l1 12h10l1-12" />
          <path d="M10 12v5" />
          <path d="M14 12v5" />
        </svg>
      );
  }
}

export type EditMode = 'view' | 'move' | 'rotate';
export type ArteryMode = 'arrow' | 'buffer' | 'off';

// DEAD_ZONE_TYPES 는 _constants.ts 로 이동 (Fast Refresh 호환 위해).

interface Props {
  /** 가벽 추가 */
  onAddWall: (length: number) => void;

  /** 선택된 오브젝트 복사 */
  onCopyObject: () => void;
  canCopy: boolean;

  /** 선택된 오브젝트 삭제 */
  onDeleteObject: () => void;
  canDelete: boolean;

  /** 팔레트에서 오브젝트 선택 시 뷰어 중앙에 추가. 두 번째 인자로 DB catalog 엔트리(있으면) 전달. */
  onAddObject: (objectType: string, catalogItem?: ObjectPaletteItem) => void;
  /** DB object_palette 목록 (GET /api/catalog/objects). null이면 로딩 중 / 실패 시 fallback */
  objectCatalog: ObjectPaletteItem[] | null;
  objectCatalogLoading?: boolean;
  objectCatalogError?: string | null;

  /** 팔레트 닫기 핸들러 */
  onClose?: () => void;
}


export default function ResultPalette({
  onAddWall,
  onCopyObject, canCopy,
  onDeleteObject, canDelete,
  onAddObject,
  objectCatalog, objectCatalogLoading, objectCatalogError,
  onClose,
}: Props) {
  // 플로팅 위치 — 보기/이동/회전 툴바 아래 캔버스 안 좌측 (헤더2줄~112px + 툴바~44px = y≈168, 좌패널~256px 우측 = x≈270)
  const PALETTE_W = 168;
  const [pos, setPos] = useState({ x: 370, y: 168 });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  // 창 크기 변경(모니터 이동 포함) 시 팔레트가 화면 밖으로 나가지 않도록 보정
  useEffect(() => {
    const onResize = () => {
      setPos(p => ({
        x: Math.min(p.x, window.innerWidth - PALETTE_W - 8),
        y: Math.min(p.y, window.innerHeight - 100),
      }));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  // 오브젝트 추가 팝오버
  const [showObjPopup, setShowObjPopup] = useState(false);
  // 가벽 프리셋 팝오버
  const [showWallPopup, setShowWallPopup] = useState(false);

  const handleHeaderMouseDown = (e: React.MouseEvent) => {
    dragRef.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({ x: ev.clientX - dragRef.current.dx, y: ev.clientY - dragRef.current.dy });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  return (
    <div
      className="fixed z-[800] bg-[#0d1526]/95 backdrop-blur-sm border border-border rounded-xl shadow-2xl select-none"
      style={{ left: pos.x, top: pos.y, width: 168 }}
    >
      {/* 헤더 — 드래그 핸들 */}
      <div
        onMouseDown={handleHeaderMouseDown}
        className="flex items-center justify-between px-2 py-1.5 border-b border-border cursor-move bg-black/30 rounded-t-xl"
      >
        <GripHorizontal size={12} className="text-text-muted" />
        <span className="text-[10px] font-bold text-text-muted tracking-wider">팔레트</span>
        {onClose
          ? <button onClick={onClose} className="text-text-muted hover:text-white transition-colors"><X size={12} /></button>
          : <span className="w-3" />
        }
      </div>

      {/* 버튼 격자 2×2 — 모든 아이콘은 PaletteIcon 단일 컴포넌트 사용 (파일 상단 참조) */}
      <div className="grid grid-cols-2 gap-1 p-1.5">
        {/* 복사 */}
        <ToolBtn
          disabled={!canCopy}
          onClick={onCopyObject}
          icon={<PaletteIcon name="copy" />}
          label="복사"
          desc="선택 항목"
        />
        {/* 삭제 */}
        <ToolBtn
          disabled={!canDelete}
          onClick={onDeleteObject}
          icon={<PaletteIcon name="trash" />}
          label="삭제"
          desc="선택 항목"
        />
        {/* 가벽 프리셋 팝업 */}
        <div className="relative">
          <ToolBtn
            active={showWallPopup}
            onClick={() => setShowWallPopup(v => !v)}
            icon={<PaletteIcon name="partition" />}
            label="가벽"
            desc="1 / 2 / 3m"
          />
          {showWallPopup && (
            <WallPresetPopup
              onPick={(length) => {
                onAddWall(length);
                setShowWallPopup(false);
              }}
              onClose={() => setShowWallPopup(false)}
            />
          )}
        </div>
        {/* 오브젝트 추가 — DB catalog 팝업 */}
        <div className="relative">
          <ToolBtn
            active={showObjPopup}
            onClick={() => setShowObjPopup(v => !v)}
            icon={<PaletteIcon name="plus" />}
            label="추가"
            desc="집기 추가"
          />
          {showObjPopup && (
            <ObjectPickerPopup
              catalog={objectCatalog}
              loading={objectCatalogLoading}
              error={objectCatalogError}
              onPick={(type, item) => {
                onAddObject(type, item);
                setShowObjPopup(false);
              }}
              onClose={() => setShowObjPopup(false)}
            />
          )}
        </div>
      </div>

    </div>
  );
}

function WallPresetPopup({
  onPick, onClose,
}: {
  onPick: (length: number) => void;
  onClose: () => void;
}) {
  return (
    <div
      className="absolute top-0 left-full ml-2 w-32 bg-[#0d1526] border border-border rounded-xl shadow-2xl z-[810] p-2"
      onClick={e => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-bold text-text-muted">가벽 길이</span>
        <button onClick={onClose} className="text-text-muted hover:text-text-main">
          <X size={11} />
        </button>
      </div>
      <div className="space-y-1">
        {WALL_PRESETS.map(({ label, length }) => (
          <button
            key={label}
            onClick={() => onPick(length)}
            className="w-full text-[11px] py-1.5 rounded border border-border bg-black/20 hover:bg-white/5 hover:border-white/30 text-text-main font-bold transition-colors"
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * 오브젝트 3D 미리보기 — cabinet projection (우측 상단에서 내려다본 느낌).
 *
 * 축 방향:
 *   width  → 화면 가로 (x)
 *   height → 화면 세로 (y, 위로)
 *   depth  → 우측 상단 30°, 0.5 스케일 (z)
 *
 * 가시 3면: front / top / right 를 같은 color 에 다른 opacity 로 명암 연출.
 * 치수 없으면 기본 1000mm 정육면체.
 */
function IsoPreview({
  code, widthMm, depthMm, heightMm,
}: {
  code: string;
  widthMm?: number;
  depthMm?: number;
  heightMm?: number;
}) {
  const color = OBJECT_COLORS[code] ?? '#e2e8f0';
  const w = widthMm && widthMm > 0 ? widthMm : 1000;
  const d = depthMm && depthMm > 0 ? depthMm : 1000;
  const h = heightMm && heightMm > 0 ? heightMm : 1000;

  const BOX = 56;
  const PAD = 4;
  const INNER = BOX - PAD * 2;

  // cabinet projection: depth 축이 30°, 0.5 스케일
  const COS30 = Math.cos(Math.PI / 6);  // ≈ 0.866
  const SIN30 = 0.5;                    // sin(30°)
  const K = 0.5;                        // depth foreshortening

  const projW = w + d * COS30 * K;
  const projH = h + d * SIN30 * K;
  const scale = INNER / Math.max(projW, projH);

  const sw = w * scale;
  const sh = h * scale;
  const dx = d * COS30 * K * scale;     // depth 가 화면 x 로 얼마만큼
  const dy = d * SIN30 * K * scale;     // depth 가 화면 y 로 얼마만큼 (위로)

  // 실제 투영된 크기 → BOX 중앙 정렬
  const svgW = sw + dx;
  const svgH = sh + dy;
  const ox = (BOX - svgW) / 2;
  const oy = (BOX - svgH) / 2;

  // 8 코너 (SVG y 는 아래로 증가, 화면 "위"는 y 작음)
  const x0 = ox;                   // front-left
  const y0 = oy + svgH;            // front-bottom (가장 아래 y)

  const FBL: [number, number] = [x0,           y0];
  const FBR: [number, number] = [x0 + sw,      y0];
  const FTL: [number, number] = [x0,           y0 - sh];
  const FTR: [number, number] = [x0 + sw,      y0 - sh];
  const BBR: [number, number] = [x0 + sw + dx, y0 - dy];
  const BTL: [number, number] = [x0 + dx,      y0 - sh - dy];
  const BTR: [number, number] = [x0 + sw + dx, y0 - sh - dy];

  const poly = (pts: [number, number][]) => pts.map(p => p.join(',')).join(' ');

  return (
    <svg width={BOX} height={BOX} viewBox={`0 0 ${BOX} ${BOX}`} className="shrink-0">
      <rect x={0} y={0} width={BOX} height={BOX} fill="#0a0f1c" rx={3} />
      {/* Right (가장 어둡게) */}
      <polygon
        points={poly([FBR, BBR, BTR, FTR])}
        fill={color} fillOpacity={0.22}
        stroke={color} strokeOpacity={0.9} strokeWidth={1}
      />
      {/* Top (가장 밝게 — 빛 받는 면) */}
      <polygon
        points={poly([FTL, FTR, BTR, BTL])}
        fill={color} fillOpacity={0.5}
        stroke={color} strokeOpacity={0.95} strokeWidth={1}
      />
      {/* Front (중간) */}
      <polygon
        points={poly([FBL, FBR, FTR, FTL])}
        fill={color} fillOpacity={0.32}
        stroke={color} strokeOpacity={0.95} strokeWidth={1}
      />
    </svg>
  );
}

function ObjectPickerPopup({
  catalog, loading, error, onPick, onClose,
}: {
  catalog: ObjectPaletteItem[] | null;
  loading?: boolean;
  error?: string | null;
  onPick: (objectType: string, item?: ObjectPaletteItem) => void;
  onClose: () => void;
}) {
  // 카탈로그 정렬: priority 내림차순 (중요한 것부터)
  const sorted = catalog
    ? [...catalog].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
    : null;
  // DB 카탈로그 없으면 OBJECT_NAMES(로컬 상수) fallback — 치수 정보 없음
  const fallback: { code: string; nameKo: string; widthStdMm?: number; depthStdMm?: number; heightStdMm?: number }[] =
    Object.entries(OBJECT_NAMES).map(([code, nameKo]) => ({ code, nameKo }));

  // 로컬 테스트 기물 머지 — DB에 이미 있는 코드는 중복 제외
  const baseItems = sorted ?? fallback;
  const baseCodes = new Set(baseItems.map(i => i.code));
  const items = [
    ...baseItems,
    ...LOCAL_TEST_FIXTURES.filter(f => !baseCodes.has(f.code)),
  ];

  return (
    <div
      className="absolute top-0 left-full ml-2 w-72 bg-[#0d1526] border border-border rounded-xl shadow-2xl z-[810] p-2"
      onClick={e => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold text-text-muted">
          오브젝트 추가 ({items.length})
        </span>
        <button onClick={onClose} className="text-text-muted hover:text-text-main">
          <X size={11} />
        </button>
      </div>

      {loading && (
        <p className="text-[10px] text-text-muted italic py-2 text-center">DB 카탈로그 로드 중...</p>
      )}
      {error && !loading && (
        <p className="text-[10px] text-red-400 italic py-1 mb-1 text-center">
          DB 로드 실패 — 로컬 fallback 사용 중
        </p>
      )}

      <div className="grid grid-cols-2 gap-1 max-h-[360px] overflow-y-auto pr-0.5">
        {items.map(item => (
          <button
            key={item.code}
            onClick={() => onPick(
              item.code,
              'widthStdMm' in item && item.widthStdMm ? (item as unknown as ObjectPaletteItem) : undefined,
            )}
            title={`${item.nameKo} (${item.code})`}
            className="flex flex-col items-center gap-1 px-1.5 py-2 rounded border border-border bg-black/20 hover:bg-white/5 hover:border-white/30 transition-colors"
          >
            <IsoPreview
              code={item.code}
              widthMm={item.widthStdMm}
              depthMm={item.depthStdMm}
              heightMm={item.heightStdMm}
            />
            <span className="text-[10px] font-bold text-text-main text-center leading-tight line-clamp-1 w-full">
              {item.nameKo}
            </span>
            {item.widthStdMm && item.depthStdMm ? (
              <span className="text-[10px] text-slate-300 leading-none font-medium">
                {item.widthStdMm}×{item.depthStdMm}
                {item.heightStdMm ? `×${item.heightStdMm}` : ''}
              </span>
            ) : (
              <span className="text-[10px] text-slate-500 leading-none">-</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── 하위 컴포넌트 ──────────────────────────────────────────

function ToolBtn({
  active, disabled, onClick, icon, label, hint, desc,
}: {
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  icon: React.ReactNode;
  label: string;
  hint?: string;
  desc?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`w-full flex flex-col items-center justify-center gap-0.5 py-3 rounded-md border transition-all ${
        disabled
          ? 'border-border bg-black/10 text-text-muted/40 cursor-not-allowed'
          : active
          ? 'border-accent/60 bg-accent/15 text-accent'
          : 'border-border bg-black/20 text-text-muted hover:text-text-main hover:border-white/30 hover:bg-white/5'
      }`}
      title={hint ? `${label} (${hint})` : label}
    >
      {icon}
      <span className="text-[9px] font-bold leading-none mt-0.5">{label}</span>
      {desc && <span className="text-[8px] leading-none opacity-50">{desc}</span>}
    </button>
  );
}

