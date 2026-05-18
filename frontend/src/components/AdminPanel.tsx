import { useNavigate } from 'react-router-dom'
import { Users, Image, ArrowLeft, ChevronRight } from 'lucide-react'

interface Props {
  onBack: () => void
}

/** /admin — 관리자 메뉴. 버튼별로 개별 라우트 (/admin/user, /admin/reference). */
export default function AdminPanel({ onBack }: Props) {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <header className="flex items-center gap-3 px-6 py-4 border-b border-slate-800">
        <button
          onClick={onBack}
          className="text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="text-white font-semibold">관리자 패널</span>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-lg space-y-4">
          <p className="text-slate-500 text-sm text-center mb-8">관리할 항목을 선택하세요.</p>

          <button
            onClick={() => navigate('/admin/user')}
            className="w-full flex items-center gap-5 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 rounded-2xl p-6 text-left transition-all group"
          >
            <div className="bg-indigo-500/10 border border-indigo-500/20 rounded-xl p-3">
              <Users size={24} className="text-indigo-400" />
            </div>
            <div className="flex-1">
              <p className="text-white font-medium mb-0.5">회원정보 조회 및 수정</p>
              <p className="text-slate-500 text-sm">가입된 회원 목록, 회원 상세 정보, 결제내역 조회하고 수정가능합니다.</p>
            </div>
            <ChevronRight size={18} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
          </button>

          <button
            onClick={() => navigate('/admin/reference')}
            className="w-full flex items-center gap-5 bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 rounded-2xl p-6 text-left transition-all group"
          >
            <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3">
              <Image size={24} className="text-emerald-400" />
            </div>
            <div className="flex-1">
              <p className="text-white font-medium mb-0.5">레퍼런스 이미지 입력</p>
              <p className="text-slate-500 text-sm">배치 추천에 사용할 레퍼런스 이미지를 관리합니다.</p>
            </div>
            <ChevronRight size={18} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
          </button>
        </div>
      </main>
    </div>
  )
}
