import { useEffect, useState } from 'react';
import {
  ChevronDown,
  RefreshCw,
  AlertCircle,
  Navigation,
  MapPinOff,
  BookOpen,
} from 'lucide-react';
import type { AnalysisReportData, InputSummary } from './mockAnalysisReport';
import { MOCK_ANALYSIS_REPORT } from './mockAnalysisReport';
import { USE_DIRECT, fetchAnalysisReportDirect } from '../../lib/api';

// ── placed_because 텍스트 클리닝 ────────────────────────────────────────
// "레퍼런스(IDOT)" 같은 내부 ID 및 "레퍼런스" 단어 제거
function cleanPlacedBecause(text: string): string {
  return text
    .replace(/레퍼런스\s*\([^)]+\)/g, '')
    .replace(/레퍼런스/g, '')
    .replace(/entrance_zone/gi, '입구 구역')
    .replace(/mid_zone/gi, '중간 구역')
    .replace(/deep_zone/gi, '안쪽 구역')
    .replace(/side_wall/gi, '측면 벽')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^:\s*/, '');
}

// ── 접기/펼치기 ──────────────────────────────────────────────────────────

function Collapsible({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg bg-slate-700/60 hover:bg-slate-600/60 border border-slate-500/60 transition-colors"
      >
        <span className="text-xs font-bold text-slate-100">{title}</span>
        <ChevronDown
          size={13}
          className={`text-slate-300 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  );
}

// ── 업로드 파일 ──────────────────────────────────────────────────────────

function InputSummarySection({ data }: { data: InputSummary }) {
  const { floor, brand, hasCrossSection } = data;
  const rows = [
    {
      label: '도면',
      applied: true,
      detail: `${floor.areaM2?.toFixed(1) ?? '-'}㎡ · 입구 ${floor.entranceCount ?? '-'}개 · 장애물 ${floor.deadZoneCount ?? '-'}곳`,
    },
    {
      label: '브랜드 매뉴얼',
      applied: brand.hasBrandManual,
      detail: brand.hasBrandManual
        ? `${brand.category} · 최소 여백 ${brand.clearspaceMm != null ? `${brand.clearspaceMm}mm` : '기본값'}`
        : '미업로드 — 일반 기준 적용',
    },
    {
      label: '단면도',
      applied: hasCrossSection,
      detail: hasCrossSection
        ? `천장 높이 ${floor.ceilingHeightMm != null ? `${floor.ceilingHeightMm.toLocaleString()}mm` : '-'}`
        : '미업로드 — 기본 높이 적용',
    },
  ];
  return (
    <div className="space-y-2">
      {rows.map(({ label, applied, detail }) => (
        <div key={label} className="flex items-center gap-2.5 text-xs">
          <span
            className={`shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded ${
              applied
                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                : 'bg-white/5 text-slate-500 border border-white/10'
            }`}
          >
            {applied ? '적용' : '미적용'}
          </span>
          <span className="font-bold text-white shrink-0">{label}</span>
          <span className="text-slate-400 text-[11px]">{detail}</span>
        </div>
      ))}
    </div>
  );
}

// ── 배치 순서 칩 선택 패널 ───────────────────────────────────────────────

function PlacementPanel({ placements }: { placements: AnalysisReportData['placements'] }) {
  const [selected, setSelected] = useState<number>(placements[0]?.rank ?? 1);
  const item = placements.find(p => p.rank === selected);

  // 종류별 집계
  const typeCounts = placements.reduce<Record<string, number>>((acc, p) => {
    acc[p.name] = (acc[p.name] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-3">

      {/* 종류별 집계 */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 pb-3 border-b border-white/10">
        {Object.entries(typeCounts).map(([name, count]) => (
          <span key={name} className="text-[11px] text-slate-400">
            {name}{' '}
            <span className="text-white font-bold">{count}개</span>
          </span>
        ))}
      </div>

      {/* 칩 목록 */}
      <p className="text-[10px] text-slate-500 mb-1.5">집기를 누르면 AI가 그 위치에 배치한 이유를 볼 수 있어요</p>
      <div className="flex flex-wrap gap-1.5">
        {placements.map(p => (
          <button
            key={p.rank}
            type="button"
            onClick={() => setSelected(p.rank)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-bold border transition-colors ${
              selected === p.rank
                ? 'bg-primary/20 border-primary/60 text-primary'
                : 'bg-white/5 border-white/10 text-slate-400 hover:text-white hover:border-white/30'
            }`}
          >
            {p.name}
          </button>
        ))}
      </div>

      {/* 선택된 집기 배치 이유 */}
      {item && (
        <div className="border-l-2 border-primary/50 pl-3 py-0.5">
          <p className="text-[11px] font-bold text-white mb-1">{item.name}</p>
          <p className="text-[11px] text-slate-400 leading-relaxed">{cleanPlacedBecause(item.placedBecause)}</p>
        </div>
      )}
    </div>
  );
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────────────

interface AnalysisReportProps {
  data?: AnalysisReportData;
}

export default function AnalysisReport({ data: dataOverride }: AnalysisReportProps = {}) {
  const [fetched, setFetched] = useState<AnalysisReportData | null>(dataOverride ?? null);
  const [loading, setLoading] = useState<boolean>(!dataOverride && USE_DIRECT);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (dataOverride || !USE_DIRECT) return;
    let alive = true;
    (async () => {
      try {
        const json = (await fetchAnalysisReportDirect()) as AnalysisReportData;
        if (alive) setFetched(json);
      } catch (e) {
        if (alive) setErrorMsg((e as Error).message ?? '리포트 데이터 로드 실패');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [dataOverride]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-400 p-8">
        <RefreshCw size={13} className="animate-spin text-primary" />
        배치 결과를 불러오는 중…
      </div>
    );
  }

  const data: AnalysisReportData = fetched ?? MOCK_ANALYSIS_REPORT;
  const isMock = !fetched;
  const { summary, placements, fireRegulation, pathCriteria, deadZones, clearance } = data;

  const hasBrandManual = data.inputSummary?.brand.hasBrandManual ?? false;
  const brandCategory = data.inputSummary?.brand.category ?? null;
  const anchor = placements[0]?.name ?? '주요 집기';
  const shortfall = summary.eligibleCount - summary.placedCount;

  return (
    <section className="fade-in space-y-2 text-xs">

      {/* 에러 / Mock 안내 */}
      {errorMsg && (
        <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          <div>
            <div>{errorMsg}</div>
            <div className="text-slate-500 mt-1">예시 데이터로 표시 중입니다.</div>
          </div>
        </div>
      )}
      {!errorMsg && isMock && (
        <div className="p-2.5 bg-amber-500/10 border border-amber-500/20 rounded-lg text-amber-400 flex items-center gap-2">
          <AlertCircle size={12} className="shrink-0" />
          예시 데이터 — 배치 실행 후 실제 결과로 갱신됩니다.
        </div>
      )}

      {/* ── 배치 결과 요약 ─────────────────────────────────────────────── */}
      <Collapsible title="배치 결과 요약" defaultOpen>
        <div className="space-y-3 text-[12px] text-slate-300 leading-[1.8]">
          <p>
            {brandCategory ? `${brandCategory} 브랜드 매장` : '매장'}을 기준으로,{' '}
            {hasBrandManual
              ? `업로드된 브랜드 매뉴얼에서 추출한 ${summary.ruleCount}개 규칙을 바탕으로`
              : `일반 VMD 기준 ${summary.ruleCount}개 규칙을 바탕으로`}{' '}
            집기 배치 초안을 작성했어요.
          </p>
          <p>
            고객 동선은{' '}
            <span className="text-white">
              {pathCriteria.zones.map(z =>
                z.label
                  .replace(/Entrance\s*·?\s*/i, '입구 공간')
                  .replace(/Mid\s*·?\s*/i, '중간 공간')
                  .replace(/Deep\s*·?\s*/i, '안쪽 공간')
                  .split('·')[0].trim()
              ).join(' → ')}
            </span>{' '}
            순으로 이어지도록 구성했으며,{' '}
            <span className="text-white font-bold">{anchor}</span>을 공간의 기준점으로 삼아
            고객이 자연스럽게 안쪽까지 이동할 수 있는 흐름을 만들었어요.
          </p>
          {deadZones.length > 0 && (
            <p>
              기둥·계단 등 {deadZones.length}곳의 배치 제외 구역을 피하고,
              소방법 기준 주동선 {fireRegulation.mainCorridorMinMm}mm를 확보하면서
              {' '}총 <span className="text-white font-bold">{summary.placedCount}개 집기</span>를 최종 배치했어요.
              {summary.eligibleCount > summary.placedCount && (
                <span className="text-amber-400/80">
                  {' '}(후보 {summary.eligibleCount}개 중 공간 제약으로 {summary.eligibleCount - summary.placedCount}개는 제외됐어요.)
                </span>
              )}
            </p>
          )}
        </div>
      </Collapsible>

      {/* ── 적용 파일 ─────────────────────────────────────────────────── */}
      <Collapsible title="적용 파일" defaultOpen>
        {data.inputSummary
          ? <InputSummarySection data={data.inputSummary} />
          : <p className="text-slate-500">파일 정보 없음</p>}
      </Collapsible>

      {/* ── 배치 결과 ─────────────────────────────────────────────────── */}
      <Collapsible title="배치 결과" defaultOpen>
        <div className="flex items-baseline gap-1.5 mb-1">
          <span className="text-3xl font-bold text-white">{summary.placedCount}</span>
          <span className="text-sm text-slate-400">개 집기가 배치됐어요</span>
        </div>

        {shortfall > 0 && (
          <p className="text-amber-400/80 text-[11px] flex items-center gap-1.5 mb-2">
            <span>⚠</span>
            {shortfall}개는 공간 부족 또는 동선 충돌로 배치하지 못했어요
          </p>
        )}

        <div className="flex flex-wrap gap-2 mt-3">
          <span className="inline-flex items-center gap-1.5 bg-white/5 border border-white/10 rounded-md px-2.5 py-1">
            <BookOpen size={11} className="text-primary" />
            <span className="text-slate-400">브랜드 가이드</span>
            <span className="font-bold text-white">{hasBrandManual ? '반영' : '기본 기준'}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 bg-white/5 border border-white/10 rounded-md px-2.5 py-1">
            <Navigation size={11} className="text-violet-400" />
            <span className="text-slate-400">주동선</span>
            <span className="font-bold text-white">{fireRegulation.mainCorridorMinMm}mm 이상</span>
          </span>
          {deadZones.length > 0 && (
            <span className="inline-flex items-center gap-1.5 bg-white/5 border border-white/10 rounded-md px-2.5 py-1">
              <MapPinOff size={11} className="text-slate-400" />
              <span className="text-slate-400">제외 구역</span>
              <span className="font-bold text-white">{deadZones.reduce((acc, dz) => {
                const n = parseInt(dz.label.match(/\d+/)?.[0] ?? '0');
                return acc + n;
              }, 0)}곳</span>
            </span>
          )}
        </div>
      </Collapsible>

      {/* ── 집기 배치 순서 및 이유 ───────────────────────────────────────── */}
      <Collapsible title="집기 배치 순서 및 이유" defaultOpen>
        <p className="text-[10px] text-slate-500 mb-3">
          유사 카테고리 매장 사례와 브랜드 가이드를 분석해 배치 순서를 결정했습니다.
        </p>
        <PlacementPanel placements={placements} />
      </Collapsible>

      {/* ── 배치 시 적용된 기준 ──────────────────────────────────────────── */}
      <Collapsible title="배치 시 적용된 기준" defaultOpen>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3.5">

          <div className="flex gap-2 items-start">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0 mt-1.5" />
            <div>
              <p className="font-bold text-white mb-0.5">고객 동선</p>
              <p className="text-slate-400 leading-relaxed">
                {pathCriteria.mainArteryDescription
                  .replace(/entrance_zone/gi, '입구 구역')
                  .replace(/mid_zone/gi, '중간 구역')
                  .replace(/deep_zone/gi, '안쪽 구역')}
              </p>
            </div>
          </div>

          <div className="flex gap-2 items-start">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0 mt-1.5" />
            <div>
              <p className="font-bold text-white mb-0.5">화재 안전 통로</p>
              <p className="text-slate-400">
                주동선 <span className="text-white font-bold">{fireRegulation.mainCorridorMinMm}mm</span>
                <span className="text-slate-600"> (약 {(fireRegulation.mainCorridorMinMm / 1000).toFixed(1)}m)</span>
                <br />비상구 <span className="text-white font-bold">{fireRegulation.emergencyPathMinMm}mm</span>
                <span className="text-slate-600"> (약 {(fireRegulation.emergencyPathMinMm / 1000).toFixed(1)}m)</span>
              </p>
            </div>
          </div>

          <div className="flex gap-2 items-start">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0 mt-1.5" />
            <div>
              <p className="font-bold text-white mb-0.5">집기 사이 여유 공간</p>
              <p className="text-slate-400">
                벽 <span className="text-white font-bold">{clearance.wallClearanceMm}mm</span>
                <span className="text-slate-600"> (약 {(clearance.wallClearanceMm / 1000).toFixed(1)}m)</span>
                <br />집기 간 <span className="text-white font-bold">{clearance.objectGapMm}mm</span>
                <span className="text-slate-600"> (약 {(clearance.objectGapMm / 1000).toFixed(1)}m)</span>
              </p>
            </div>
          </div>

          {deadZones.length > 0 && (
            <div className="flex gap-2 items-start">
              <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0 mt-1.5" />
              <div>
                <p className="font-bold text-white mb-0.5">배치 제외 구역</p>
                <p className="text-slate-400 leading-relaxed">
                  {deadZones.map(dz => dz.label).join(' · ')}
                </p>
              </div>
            </div>
          )}

          <div className="flex gap-2 items-start">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400 shrink-0 mt-1.5" />
            <div>
              <p className="font-bold text-white mb-0.5">구역 분류</p>
              <p className="text-slate-400 leading-relaxed whitespace-pre-line">
                {pathCriteria.zones
                  .map(z => z.label
                    .replace(/Entrance\s*·?\s*/i, '입구 공간 · ')
                    .replace(/Mid\s*·?\s*/i, '중간 공간 · ')
                    .replace(/Deep\s*·?\s*/i, '안쪽 공간 · ')
                    .replace(/감압 및 후킹/g, '첫 인상')
                    .replace(/핵심 제품 관여 및 순환/g, '메인 진열')
                    .replace(/목적지 및 백오피스/g, '결제·피팅')
                  )
                  .join('\n')}
              </p>
            </div>
          </div>

        </div>
      </Collapsible>

    </section>
  );
}
