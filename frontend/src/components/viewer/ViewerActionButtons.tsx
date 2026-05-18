/**
 * ViewerActionButtons — Viewer3D 우측 기능 버튼 그룹.
 */
import { useEffect, useRef, useState } from 'react';
import { LayoutGrid, Ban, Columns2, Route, GitBranch, Layers } from 'lucide-react';
import { useToast } from '../../context/ToastContext';

const FLOOR_OPTIONS: { key: string | null; label: string; color: string }[] = [
  { key: null,       label: '기본',    color: '#f8fafc' },
  { key: 'wood',     label: '원목',    color: '#c8a882' },
  { key: 'tile',     label: '타일',    color: '#f0f0f0' },
  { key: 'concrete', label: '콘크리트', color: '#d4d4d4' },
  { key: 'terrazzo', label: '테라조',  color: '#e8e0d8' },
  { key: 'marble',   label: '대리석',  color: '#f0ece8' },
]

interface Props {
  onTogglePalette?: () => void;
  paletteActive?: boolean;
  showDeadZones: boolean;
  setShowDeadZones: (v: boolean | ((prev: boolean) => boolean)) => void;
  hasDeadZones?: boolean;
  showWalls: boolean;
  setShowWalls: (v: boolean | ((prev: boolean) => boolean)) => void;
  hasWalls?: boolean;
  arteryMode: 'arrow' | 'buffer' | 'off';
  setArteryMode: (v: ((prev: 'arrow' | 'buffer' | 'off') => 'arrow' | 'buffer' | 'off')) => void;
  hasArtery?: boolean;
  subPathVisible: boolean;
  setSubPathVisible: (v: boolean | ((prev: boolean) => boolean)) => void;
  hasSubPath?: boolean;
  floorTextureKey: string | null;
  setFloorTextureKey: (key: string | null) => void;
  /** 컨셉구역 정의 (key, label, color). 없으면 섹션 미표시 */
  conceptAreaDefs?: { key: string; label: string; color: string }[];
  /** 숨겨진 컨셉구역 key Set */
  hiddenConceptAreaKeys?: Set<string>;
  /** 개별 컨셉구역 토글 */
  onToggleConceptArea?: (key: string) => void;
  /** 전체 ON/OFF 토글 */
  onToggleAllConceptAreas?: () => void;
}

const btn = (active: boolean) =>
  `flex items-center gap-2 px-2.5 py-1.5 text-[11px] font-medium rounded-lg transition-all border whitespace-nowrap ${
    active
      ? 'bg-slate-700 text-white border-slate-700 hover:bg-slate-600'
      : 'bg-white text-slate-400 border-slate-200 hover:border-slate-400 hover:text-slate-600'
  }`;

function Dot({ active }: { active: boolean }) {
  return (
    <span className={`w-2 h-2 rounded-full shrink-0 transition-colors ${
      active ? 'bg-emerald-400' : 'bg-slate-300'
    }`} />
  );
}

export default function ViewerActionButtons({
  onTogglePalette,
  paletteActive,
  showDeadZones, setShowDeadZones, hasDeadZones = false,
  showWalls, setShowWalls, hasWalls = false,
  arteryMode, setArteryMode, hasArtery = false,
  subPathVisible, setSubPathVisible, hasSubPath = false,
  floorTextureKey, setFloorTextureKey,
  conceptAreaDefs, hiddenConceptAreaKeys, onToggleConceptArea, onToggleAllConceptAreas,
}: Props) {
  const { toast } = useToast();
  const arteryOn = arteryMode !== 'off';
  const [floorPickerOpen, setFloorPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!floorPickerOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (!pickerRef.current?.contains(e.target as Node)) setFloorPickerOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [floorPickerOpen]);

  const handleDeadZone = () => {
    if (!hasDeadZones) { toast.info('감지된 이격구역이 없습니다'); return; }
    setShowDeadZones(v => !v);
  };
  const handleWalls = () => {
    if (!hasWalls) { toast.info('감지된 벽체가 없습니다'); return; }
    setShowWalls(v => !v);
  };
  const handleArtery = () => {
    if (!hasArtery) { toast.info('동선 데이터가 없습니다'); return; }
    setArteryMode(m => m !== 'off' ? 'off' : 'arrow');
  };
  const handleSubPath = () => {
    if (!hasSubPath) { toast.info('부동선 데이터가 없습니다'); return; }
    setSubPathVisible(v => !v);
  };

  const hasConceptAreas = (conceptAreaDefs?.length ?? 0) > 0 && !!onToggleConceptArea;
  const allConceptAreasOn = hasConceptAreas && (hiddenConceptAreaKeys?.size ?? 0) === 0;
  const floorActive = floorTextureKey !== null || (hasConceptAreas && !allConceptAreasOn);

  return (
    <div className="flex flex-wrap items-center gap-2 justify-end">

      {onTogglePalette && (
        <button onClick={onTogglePalette} className={btn(!!paletteActive)} title="팔레트 열기/닫기">
          <LayoutGrid size={12} />
          팔레트
          <Dot active={!!paletteActive} />
        </button>
      )}

      <button onClick={handleDeadZone} className={btn(showDeadZones && hasDeadZones)}>
        <Ban size={12} />
        이격구역
        <Dot active={showDeadZones && hasDeadZones} />
      </button>

      <button onClick={handleWalls} className={btn(showWalls && hasWalls)}>
        <Columns2 size={12} />
        벽체
        <Dot active={showWalls && hasWalls} />
      </button>

      <button onClick={handleArtery} className={btn(arteryOn && hasArtery)}>
        <Route size={12} />
        동선
        <Dot active={arteryOn && hasArtery} />
      </button>

      <button onClick={handleSubPath} className={btn(subPathVisible && hasSubPath)}>
        <GitBranch size={12} />
        부동선
        <Dot active={subPathVisible && hasSubPath} />
      </button>

      {/* 바닥 (바닥재 패턴 + 컨셉구역) */}
      <div className="relative" ref={pickerRef}>
        <button
          onClick={() => setFloorPickerOpen(v => !v)}
          className={btn(floorActive)}
          title="바닥 설정"
        >
          <Layers size={12} />
          바닥
          <Dot active={floorActive} />
        </button>
        {floorPickerOpen && (
          <div className="absolute right-0 top-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg p-1.5 z-50 flex flex-col gap-0.5 w-32">
            {/* 바닥재 패턴 */}
            <div className="px-1 pt-0.5 pb-1">
              <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wide">바닥재</span>
            </div>
            {FLOOR_OPTIONS.map(opt => (
              <button
                key={String(opt.key)}
                onClick={() => { setFloorTextureKey(opt.key); }}
                className={`flex items-center gap-2 px-2 py-1.5 rounded text-[11px] text-left transition-colors ${
                  floorTextureKey === opt.key
                    ? 'bg-slate-100 text-slate-800 font-semibold'
                    : 'text-slate-600 hover:bg-slate-50'
                }`}
              >
                <span
                  className="w-3.5 h-3.5 rounded-sm border border-slate-300 shrink-0"
                  style={{ background: opt.color }}
                />
                {opt.label}
              </button>
            ))}

            {/* 컨셉구역 */}
            {hasConceptAreas && (
              <>
                <div className="border-t border-slate-100 mx-1 my-0.5" />
                <div className="flex items-center justify-between px-1 pt-0.5 pb-1">
                  <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-wide">컨셉구역</span>
                  {onToggleAllConceptAreas && (
                    <button
                      onClick={onToggleAllConceptAreas}
                      className="text-[9px] text-slate-400 hover:text-slate-600 transition-colors"
                    >
                      {(hiddenConceptAreaKeys?.size ?? 0) >= (conceptAreaDefs?.length ?? 0) ? '전체 ON' : '전체 OFF'}
                    </button>
                  )}
                </div>
                {conceptAreaDefs!.map(({ key, label, color }) => {
                  const on = !hiddenConceptAreaKeys?.has(key);
                  return (
                    <button
                      key={key}
                      onClick={() => onToggleConceptArea!(key)}
                      className={`flex items-center gap-2 px-2 py-1.5 rounded text-[11px] text-left transition-colors ${
                        on ? 'text-slate-700 hover:bg-slate-50' : 'text-slate-400 hover:bg-slate-50 opacity-60'
                      }`}
                    >
                      <span className="w-3.5 h-3.5 rounded-full shrink-0 border border-slate-200" style={{ background: color }} />
                      <span className="flex-1">{label}</span>
                      <span className="text-[9px] text-slate-400">{on ? 'ON' : 'OFF'}</span>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        )}
      </div>

    </div>
  );
}
