import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

/** /admin/feedback — 사용자 배치 피드백 관리. 현재 더미 데이터. */
export default function AdminFeedbackPage() {
  const navigate = useNavigate()

  // 더미 데이터 — 실제는 GET /api/admin/feedback
  const dummy = [
    { id: 1, user: '테스터', project: '강남점 v1', type: 'dislike',   date: '2026-04-15', message: '배치가 너무 꽉 차 보여요' },
    { id: 2, user: '희영',   project: '홍대점 v2', type: 'bad_layout', date: '2026-04-14', message: '입구 정면에 포토존 가림' },
  ]

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <header className="flex items-center gap-3 px-6 py-4 border-b border-slate-800">
        <button
          onClick={() => navigate('/admin')}
          className="text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="text-white font-semibold">피드백 관리</span>
      </header>

      <main className="flex-1 px-6 py-6">
        <div className="max-w-3xl mx-auto">
          <p className="text-[11px] text-amber-400 mb-3">
            ⚠ 더미 데이터 — `placement_feedback` 테이블 + 백엔드 API 연동 대기 중
          </p>

          <div className="space-y-2">
            {dummy.map(f => (
              <div key={f.id} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="text-white text-sm font-medium">{f.project}</p>
                    <p className="text-slate-500 text-xs mt-0.5">
                      {f.user} · {f.date} ·
                      <span className={`ml-1 ${f.type === 'dislike' ? 'text-amber-400' : 'text-red-400'}`}>
                        {f.type}
                      </span>
                    </p>
                  </div>
                  <div className="flex gap-1.5">
                    <button
                      disabled
                      className="text-xs text-slate-500 border border-slate-700 px-2 py-1 rounded-lg opacity-40 cursor-not-allowed"
                    >
                      블랙리스트
                    </button>
                    <button
                      disabled
                      className="text-xs text-slate-500 border border-slate-700 px-2 py-1 rounded-lg opacity-40 cursor-not-allowed"
                    >
                      재배치
                    </button>
                  </div>
                </div>
                <p className="text-slate-300 text-sm bg-slate-950/60 rounded-lg px-3 py-2">
                  {f.message}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-6 bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
            <p className="text-xs text-amber-400 font-bold mb-2">구현 필요 항목</p>
            <ul className="text-[11px] text-slate-400 space-y-1 list-disc pl-4">
              <li>사용자측: ResultPage에 "배치 마음에 안들어요" 버튼 + 입력 모달</li>
              <li>백엔드: POST /api/feedback, GET /api/admin/feedback, 블랙리스트/재배치 API</li>
              <li>DB: placement_feedback 테이블 + 블랙리스트 관리 필드</li>
            </ul>
          </div>
        </div>
      </main>
    </div>
  )
}
