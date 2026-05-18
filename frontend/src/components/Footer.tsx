import { Box as BoxIcon, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function Footer() {
  return (
    <footer className="border-t border-white/[0.04]">
      <div className="max-w-5xl mx-auto px-6 py-2">
        <div className="flex justify-between gap-8 mb-2">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className="bg-primary p-1.5 rounded-lg shadow-lg ring-2 ring-primary/20">
                <BoxIcon size={16} className="text-white" />
              </div>
              <h3 className="text-sm font-bold hero-gradient">LandUP</h3>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed">팝업스토어 VMD 담당자를 위한<br />AI 공간 배치 자동화 서비스</p>
          </div>
          <div>
            <h3 className="text-xs font-semibold text-white mb-2 uppercase tracking-wider">서비스</h3>
            <ul className="space-y-1.5 text-xs text-slate-600">
              <li>도면 자동 분석</li>
              <li>AI 배치 제안</li>
              <li>GLB 내보내기</li>
            </ul>
          </div>
          <div>
            <h3 className="text-xs font-semibold text-white mb-2 uppercase tracking-wider">지원</h3>
            <ul className="space-y-1.5 text-xs text-slate-600">
              <li><Link to="/pay" className="hover:text-slate-400 transition-colors">이용 안내</Link></li>
              <li><Link to="/pay" className="hover:text-slate-400 transition-colors">요금제</Link></li>
              <li>문의하기</li>
            </ul>
          </div>
          <div>
            <h3 className="text-xs font-semibold text-white mb-2 uppercase tracking-wider">SNS</h3>
            <ul className="space-y-1.5">
              {[
                { label: 'Instagram', href: 'https://www.instagram.com' },
                { label: 'Youtube',   href: 'https://www.youtube.com' },
                { label: 'Facebook',  href: 'https://www.facebook.com' },
              ].map(({ label, href }) => (
                <li key={label}>
                  <a href={href} target="_blank" rel="noopener noreferrer"
                     className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-400 transition-colors">
                    {label} <ExternalLink size={11} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
      <div className="border-t border-white/[0.06] pt-2 pb-2 px-6">
        <div className="max-w-5xl mx-auto">
          <p className="text-xs text-slate-600">(주) 랜드업</p>
          <p className="text-xs text-slate-600 mb-2">서울 서초구 강남대로 405 통영빌딩 8층</p>
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-600">© 2026 LandUP. All rights reserved.</p>
            <div className="flex items-center gap-4 text-xs text-slate-600">
              <span>개인정보처리방침</span>
              <span>이용약관</span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  )
}
