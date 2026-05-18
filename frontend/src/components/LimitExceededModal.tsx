import { X, Zap, ArrowUpCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

interface Props {
  message: string
  membership: string
  onClose: () => void
}

export default function LimitExceededModal({ message, membership, onClose }: Props) {
  const navigate = useNavigate()
  const isBasic = membership.toLowerCase() === 'basic'
  const isMax = membership.toLowerCase() === 'max'

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="text-sm font-bold text-white">월 사용한도 초과</span>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-5 space-y-3">
          <p className="text-sm text-slate-300 leading-relaxed">{message}</p>

          {isBasic ? (
            <button
              onClick={() => { onClose(); navigate('/pay') }}
              className="w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 bg-primary text-white hover:bg-primary/90"
            >
              <ArrowUpCircle size={15} /> 플랜 업그레이드
            </button>
          ) : isMax ? (
            <button
              onClick={() => { onClose(); navigate('/mypage') }}
              className="w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 bg-primary text-white hover:bg-primary/90"
            >
              <Zap size={15} /> 크레딧 구매하러 가기
            </button>
          ) : (
            <>
              <button
                onClick={() => { onClose(); navigate('/pay') }}
                className="w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 bg-amber-400/10 text-amber-400 border border-amber-400/30 hover:bg-amber-400/20"
              >
                <ArrowUpCircle size={15} /> 상위 플랜으로 업그레이드
              </button>
              <button
                onClick={() => { onClose(); navigate('/mypage') }}
                className="w-full py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 bg-white/5 text-slate-300 border border-border hover:bg-white/10"
              >
                <Zap size={15} /> 크레딧 구매하러 가기
              </button>
            </>
          )}

          <button
            onClick={onClose}
            className="w-full py-2.5 rounded-xl text-sm text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  )
}
