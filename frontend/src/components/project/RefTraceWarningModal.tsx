/**
 * RefTraceWarningModal - 레퍼런스 반영도 모달
 *
 * 디자인 참조 로직 트랙 8번 (사용자 경고/확인 모달).
 *
 * 표시 방식 (사용자 결정 2026-05-04) - 수동.
 * 자동 표시 X (무한 모달 방지). ResultPage 사이드바 점수 배지 클릭 시만 표시.
 *
 * 점수별 분기 (2026-05-04 사용자 지적 - 0.93 인데 "낮음" 뜨던 버그 수정):
 * - score < 0.4 = 낮음 (빨강) - "다시 생성" primary 강조
 * - 0.4 부터 0.7 미만 = 보통 (노랑) - "다시 생성" secondary
 * - score >= 0.7 = 우수 (초록) - "다시 생성" tertiary (사용자가 굳이 원하면)
 *
 * Props:
 * - score: ref_quality_score (0.0 부터 1.0)
 * - onRetry: "다시 생성" 클릭 시 호출 (handleReplace 등)
 * - onClose: "그대로 사용" 또는 X 버튼 클릭 시 호출
 */
import { X, RefreshCw, Check } from 'lucide-react'

interface Props {
  score: number
  onRetry: () => void
  onClose: () => void
}

type Tier = 'low' | 'mid' | 'high'

function classifyScore(score: number): Tier {
  if (score < 0.4) return 'low'
  if (score < 0.7) return 'mid'
  return 'high'
}

const TIER_CONFIG: Record<Tier, {
  headerLabel: string
  headerColor: string
  bodyText: string
  bodyAccent: string
  retryClass: string
}> = {
  low: {
    headerLabel: '레퍼런스 반영도 낮음',
    headerColor: 'text-red-300',
    bodyText: '이 배치는 레퍼런스 분석 패턴이 거의 반영되지 않았습니다. LLM 이 레퍼런스 무시하고 자체 판단으로 배치한 케이스로 추정됩니다.',
    bodyAccent: 'text-red-400',
    retryClass: 'bg-red-500/80 text-white hover:bg-red-500',
  },
  mid: {
    headerLabel: '레퍼런스 반영도 보통',
    headerColor: 'text-yellow-300',
    bodyText: '일부 레퍼런스 패턴이 반영됐지만 빠진 부분도 있습니다. 더 충실한 반영을 원하면 다시 생성해보세요.',
    bodyAccent: 'text-yellow-400',
    retryClass: 'bg-primary text-white hover:bg-primary/90',
  },
  high: {
    headerLabel: '레퍼런스 반영도 우수',
    headerColor: 'text-green-300',
    bodyText: '레퍼런스 분석 패턴이 잘 반영된 배치입니다. 그대로 사용해도 좋습니다.',
    bodyAccent: 'text-green-400',
    retryClass: 'bg-white/10 text-slate-200 border border-border hover:bg-white/20',
  },
}

export default function RefTraceWarningModal({ score, onRetry, onClose }: Props) {
  const scoreText = score.toFixed(2)
  const scorePct = Math.round(score * 100)
  const tier = classifyScore(score)
  const cfg = TIER_CONFIG[tier]

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-md mx-4 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className={`text-sm font-bold ${cfg.headerColor}`}>{cfg.headerLabel}</span>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-5 space-y-4">
          <p className="text-sm text-slate-300 leading-relaxed">
            점수: <span className={`font-mono font-bold ${cfg.bodyAccent}`}>{scoreText}</span> / 1.00 ({scorePct}%)
            <br />
            {cfg.bodyText}
          </p>

          <div className="bg-slate-900/50 rounded-lg px-3 py-2.5 text-xs text-slate-400 leading-relaxed">
            <span className="text-slate-500">참고:</span> 레퍼런스 반영도 = 레퍼런스 이미지 분석 패턴이 실제 배치에 얼마나 반영됐는지의 점수.
            낮은 점수일수록 LLM 이 레퍼런스 무시하고 자체 판단으로 배치한 케이스입니다.
          </div>

          <div className="flex flex-col gap-2">
            <button
              onClick={() => { onClose(); onRetry() }}
              className={`w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 ${cfg.retryClass}`}
            >
              <RefreshCw size={15} /> 다시 생성
            </button>
            <button
              onClick={onClose}
              className="w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 bg-white/5 text-slate-300 border border-border hover:bg-white/10"
            >
              <Check size={15} /> 그대로 사용
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
