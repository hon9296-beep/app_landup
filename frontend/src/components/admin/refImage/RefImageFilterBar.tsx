/**
 * 관리자 레퍼런스 이미지 페이지 상단 필터 바.
 *
 * 필터 3종:
 *   1. 도면 사이즈 dropdown — small / medium / large / outdoor
 *   2. 카테고리 dropdown + 검색 input 토글 (돋보기 버튼)
 *   3. 날짜 단일 선택 — native <input type="date">
 *      (MVP. 범위 선택 / 분기별은 후속. ref 이미지 등록 없는 날 비활성은 후속)
 *
 * 스타일 가이드 엄수: border-border / rounded-lg / text-xs / font-bold.
 */
import { useRef, useState } from 'react';
import { Search, X, Calendar } from 'lucide-react';
import type { FloorSizeTier, BrandCategory } from './types';

export interface FilterValues {
  floorSizeTier: FloorSizeTier | 'all';
  brandCategoryId: number | 'all';
  searchKeyword: string;       // 카테고리 검색어 (검색 모드일 때만)
  date: string | 'all';        // YYYY-MM-DD 또는 'all'
}

interface Props {
  value: FilterValues;
  onChange: (v: FilterValues) => void;
  categories: BrandCategory[];
}

const TIER_LABEL: Record<FloorSizeTier, string> = {
  small: '소형 (5~20평)',
  medium: '중형 (20~50평)',
  large: '대형 (50평~)',
  outdoor: '야외',
};

export default function RefImageFilterBar({ value, onChange, categories }: Props) {
  const [searchMode, setSearchMode] = useState(false);
  const dateInputRef = useRef<HTMLInputElement>(null);

  const openDatePicker = () => {
    const el = dateInputRef.current;
    if (!el) return;
    // 최신 브라우저 — showPicker 로 명시적 호출 (클릭 범위 넓히기 + 안정성)
    if (typeof el.showPicker === 'function') {
      try { el.showPicker(); return; } catch { /* fallthrough */ }
    }
    el.focus();
    el.click();
  };

  return (
    <div className="flex flex-wrap items-center gap-3 pb-4 border-b border-border">
      {/* 도면 사이즈 */}
      <select
        value={value.floorSizeTier}
        onChange={(e) =>
          onChange({ ...value, floorSizeTier: e.target.value as FilterValues['floorSizeTier'] })
        }
        className="bg-white/5 border border-border rounded-lg px-3 py-1.5 text-xs text-white font-bold focus:outline-none focus:border-primary"
      >
        <option value="all" className="bg-slate-900 text-white">도면 사이즈 (전체)</option>
        <option value="small" className="bg-slate-900 text-white">{TIER_LABEL.small}</option>
        <option value="medium" className="bg-slate-900 text-white">{TIER_LABEL.medium}</option>
        <option value="large" className="bg-slate-900 text-white">{TIER_LABEL.large}</option>
        <option value="outdoor" className="bg-slate-900 text-white">{TIER_LABEL.outdoor}</option>
      </select>

      {/* 카테고리: 돋보기 + dropdown/검색 input 을 단일 박스로 묶음 */}
      {!searchMode ? (
        <div className="flex items-center bg-white/5 border border-border rounded-lg overflow-hidden focus-within:border-primary transition-colors">
          <button
            type="button"
            onClick={() => setSearchMode(true)}
            className="p-2 hover:bg-white/10 border-r border-border transition-colors"
            aria-label="카테고리 검색 input 으로 전환"
            title="이름 검색"
          >
            <Search size={13} className="text-slate-400" />
          </button>
          <select
            value={value.brandCategoryId}
            onChange={(e) =>
              onChange({
                ...value,
                brandCategoryId:
                  e.target.value === 'all' ? 'all' : Number(e.target.value),
              })
            }
            className="bg-transparent px-3 py-1.5 text-xs text-white font-bold focus:outline-none"
          >
            <option value="all" className="bg-slate-900 text-white">카테고리 (전체)</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id} className="bg-slate-900 text-white">
                {c.nameKo}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <div className="flex items-center bg-white/5 border border-border rounded-lg overflow-hidden focus-within:border-primary transition-colors">
          <button
            type="button"
            onClick={() => {
              setSearchMode(false);
              onChange({ ...value, searchKeyword: '' });
            }}
            className="p-2 hover:bg-white/10 border-r border-border transition-colors"
            aria-label="검색 해제"
          >
            <X size={13} className="text-slate-400" />
          </button>
          <input
            type="text"
            autoFocus
            placeholder="카테고리 이름 검색..."
            value={value.searchKeyword}
            onChange={(e) => onChange({ ...value, searchKeyword: e.target.value })}
            className="bg-transparent px-3 py-1.5 text-xs text-white font-bold focus:outline-none w-48"
          />
        </div>
      )}

      {/* 날짜 단일 선택 — 전체 박스 클릭으로 네이티브 달력 호출 */}
      <div
        onClick={openDatePicker}
        className="flex items-center bg-white/5 border border-border rounded-lg overflow-hidden cursor-pointer focus-within:border-primary hover:bg-white/10 transition-colors"
      >
        <div className="p-2 border-r border-border pointer-events-none">
          <Calendar size={13} className="text-white" />
        </div>
        <input
          ref={dateInputRef}
          type="date"
          value={value.date === 'all' ? '' : value.date}
          onChange={(e) =>
            onChange({ ...value, date: e.target.value || 'all' })
          }
          style={{ colorScheme: 'dark' }}
          className="bg-transparent px-3 py-1.5 text-xs text-white font-bold focus:outline-none cursor-pointer [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
        />
        {value.date !== 'all' && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onChange({ ...value, date: 'all' });
            }}
            className="px-2 py-1.5 text-[11px] text-slate-400 hover:text-white hover:bg-white/10 border-l border-border transition-colors"
          >
            초기화
          </button>
        )}
      </div>
    </div>
  );
}
