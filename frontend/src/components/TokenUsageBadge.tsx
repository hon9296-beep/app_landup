/**
 * TokenUsageBadge — 좌하단 LLM 비용 누적 배지 (개발용).
 *
 * 표시: 토큰 / $ / ₩ 한 줄. 클릭 → 모달 (모델별 + 노드별 + 리셋).
 *
 * 갱신 (옵션 A — 폴링 없음):
 *  - 마운트 시 1회 fetch
 *  - 모달 open 시 즉시 fetch
 *  - 리셋 후 즉시 fetch
 *  - (자동 폴링 제거 2026-05-07 — 백엔드 로그/네트워크 패널 노이즈 방지)
 *
 * 호환:
 *  - USE_DIRECT 모드 (Python 직통) 에서 정상 동작
 *  - Java 경유 모드에서는 Java 라우팅 미구현 시 404 → 자동 hide
 */
import { useEffect, useState } from 'react'
import { Coins, X, RotateCcw } from 'lucide-react'
import { getTokenCumulative, resetTokenUsage, type TokenCumulative, type BucketStats } from '../lib/tokenUsageApi'

function formatNumber(n: number): string {
  return n.toLocaleString('ko-KR')
}

function formatUSD(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

function formatKRW(n: number): string {
  return `₩${formatNumber(Math.round(n))}`
}

function StatRow({ label, stats }: { label: string; stats: BucketStats }) {
  return (
    <tr className="border-b border-border/40 text-xs">
      <td className="py-1.5 px-2 text-text-main truncate max-w-[200px]" title={label}>{label}</td>
      <td className="py-1.5 px-2 text-right text-text-muted">{formatNumber(stats.calls)}</td>
      <td className="py-1.5 px-2 text-right text-text-muted">{formatNumber(stats.input)}</td>
      <td className="py-1.5 px-2 text-right text-text-muted">{formatNumber(stats.output)}</td>
      <td className="py-1.5 px-2 text-right text-text-muted">{formatNumber(stats.cache_read)}</td>
      <td className="py-1.5 px-2 text-right text-emerald-400">{formatUSD(stats.cost_usd)}</td>
    </tr>
  )
}

function UsageModal({
  data,
  onClose,
  onReset,
}: {
  data: TokenCumulative
  onClose: () => void
  onReset: () => void
}) {
  const [resetting, setResetting] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  const handleReset = async () => {
    if (!confirmReset) {
      setConfirmReset(true)
      return
    }
    setResetting(true)
    try {
      await resetTokenUsage()
      onReset()
    } finally {
      setResetting(false)
      setConfirmReset(false)
    }
  }

  const modelEntries = Object.entries(data.by_model).sort((a, b) => b[1].cost_usd - a[1].cost_usd)
  const nodeEntries = Object.entries(data.by_node).sort((a, b) => b[1].cost_usd - a[1].cost_usd)

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-end justify-start p-4"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-border rounded-xl shadow-2xl w-full max-w-3xl max-h-[80vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border sticky top-0 bg-slate-900 z-10">
          <div className="flex items-center gap-2">
            <Coins size={16} className="text-amber-400" />
            <h2 className="text-sm font-semibold text-text-main">LLM 비용 누적</h2>
          </div>
          <button onClick={onClose} className="text-text-muted hover:text-white p-1">
            <X size={16} />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* 총 요약 */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-[10px] text-text-muted">총 토큰</div>
              <div className="text-lg font-bold text-text-main">{formatNumber(data.total_tokens)}</div>
              <div className="text-[10px] text-text-muted mt-0.5">호출 {data.total_calls}회</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-[10px] text-text-muted">USD</div>
              <div className="text-lg font-bold text-emerald-400">{formatUSD(data.total_cost_usd)}</div>
              <div className="text-[10px] text-text-muted mt-0.5">$1 = ₩{formatNumber(data.usd_to_krw)}</div>
            </div>
            <div className="bg-slate-800/50 rounded-lg p-3">
              <div className="text-[10px] text-text-muted">KRW</div>
              <div className="text-lg font-bold text-amber-300">{formatKRW(data.total_cost_krw)}</div>
              <div className="text-[10px] text-text-muted mt-0.5">
                {data.started_at ? `시작 ${new Date(data.started_at).toLocaleTimeString('ko-KR')}` : '기록 없음'}
              </div>
            </div>
          </div>

          {/* 모델별 */}
          <div>
            <h3 className="text-xs font-semibold text-text-main mb-1.5">모델별</h3>
            <div className="bg-slate-800/30 rounded-lg overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] text-text-muted border-b border-border">
                    <th className="py-1.5 px-2 text-left font-normal">모델</th>
                    <th className="py-1.5 px-2 text-right font-normal">호출</th>
                    <th className="py-1.5 px-2 text-right font-normal">input</th>
                    <th className="py-1.5 px-2 text-right font-normal">output</th>
                    <th className="py-1.5 px-2 text-right font-normal">cache R</th>
                    <th className="py-1.5 px-2 text-right font-normal">USD</th>
                  </tr>
                </thead>
                <tbody>
                  {modelEntries.length === 0 ? (
                    <tr><td colSpan={6} className="py-4 px-2 text-center text-xs text-text-muted">데이터 없음</td></tr>
                  ) : (
                    modelEntries.map(([model, stats]) => (
                      <StatRow key={model} label={model} stats={stats} />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 노드별 */}
          <div>
            <h3 className="text-xs font-semibold text-text-main mb-1.5">노드별 (어디에 썼나)</h3>
            <div className="bg-slate-800/30 rounded-lg overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] text-text-muted border-b border-border">
                    <th className="py-1.5 px-2 text-left font-normal">노드</th>
                    <th className="py-1.5 px-2 text-right font-normal">호출</th>
                    <th className="py-1.5 px-2 text-right font-normal">input</th>
                    <th className="py-1.5 px-2 text-right font-normal">output</th>
                    <th className="py-1.5 px-2 text-right font-normal">cache R</th>
                    <th className="py-1.5 px-2 text-right font-normal">USD</th>
                  </tr>
                </thead>
                <tbody>
                  {nodeEntries.length === 0 ? (
                    <tr><td colSpan={6} className="py-4 px-2 text-center text-xs text-text-muted">데이터 없음</td></tr>
                  ) : (
                    nodeEntries.map(([node, stats]) => (
                      <StatRow key={node} label={node} stats={stats} />
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* 리셋 */}
          <div className="flex justify-end pt-2 border-t border-border">
            <button
              onClick={handleReset}
              disabled={resetting}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg transition-all border ${
                confirmReset
                  ? 'bg-red-500/20 border-red-500/50 text-red-300 hover:bg-red-500/30'
                  : 'border-border text-text-muted hover:text-white hover:border-white/30'
              }`}
            >
              <RotateCcw size={12} />
              {resetting ? '리셋 중...' : confirmReset ? '한번 더 눌러서 0으로' : '0 으로 리셋'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function TokenUsageBadge() {
  const [data, setData] = useState<TokenCumulative | null>(null)
  const [open, setOpen] = useState(false)
  const [available, setAvailable] = useState(true)

  const fetchData = async () => {
    try {
      const d = await getTokenCumulative()
      setData(d)
      setAvailable(true)
    } catch {
      // 백엔드 미연결 / Java 라우팅 미구현 시 hide
      setAvailable(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  if (!available || !data) return null

  return (
    <>
      <button
        onClick={() => { setOpen(true); fetchData() }}
        className="fixed bottom-4 left-4 z-40 flex items-center gap-2 bg-slate-900/90 backdrop-blur border border-border hover:border-amber-400/40 px-3 py-2 rounded-xl shadow-lg transition-all text-xs"
        title={`호출 ${data.total_calls}회 · 마지막 ${data.updated_at ? new Date(data.updated_at).toLocaleTimeString('ko-KR') : '없음'}`}
      >
        <Coins size={13} className="text-amber-400" />
        <span className="text-text-main font-medium">{formatNumber(data.total_tokens)}</span>
        <span className="text-text-muted">·</span>
        <span className="text-emerald-400 font-medium">{formatUSD(data.total_cost_usd)}</span>
        <span className="text-text-muted">·</span>
        <span className="text-amber-300 font-medium">{formatKRW(data.total_cost_krw)}</span>
      </button>

      {open && data && (
        <UsageModal
          data={data}
          onClose={() => setOpen(false)}
          onReset={fetchData}
        />
      )}
    </>
  )
}
