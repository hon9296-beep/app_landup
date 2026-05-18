/**
 * AuthLayout — 로그인/회원가입/OAuth 콜백 전용 레이아웃
 * 헤더는 없지만 좌상단에 "← 홈으로" 버튼만 얹어서 이탈 가능하게
 */
import { Link, Outlet } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Footer from '../components/Footer';

export default function AuthLayout() {
  return (
    <div className="flex flex-col min-h-screen bg-slate-950">
      <header className="fixed top-0 left-0 right-0 z-10 flex items-center gap-3 px-6 py-4">
        <Link
          to="/"
          className="flex items-center gap-1.5 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={16} />
          <span className="text-xs">홈으로</span>
        </Link>
      </header>
      <Outlet />
      <Footer />
    </div>
  );
}
