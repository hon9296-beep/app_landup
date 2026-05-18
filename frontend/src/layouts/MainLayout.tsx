/**
 * MainLayout — 공통 헤더 + Outlet
 * 사용처: /, /app, /mypage, /pay, /admin 등 (로그인/콜백 제외)
 */
import { useState, useRef, useEffect } from 'react';
import { Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Box, ChevronDown, User, CreditCard, LogOut, ShieldCheck, LayoutDashboard } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { isAdmin } from '../routes/AdminRoute';
import ActiveJobBadge from '../components/ActiveJobBadge';
import Footer from '../components/Footer';
import { USE_DIRECT } from '../lib/api';
import { API_BASE } from '../lib/axiosClient';

function ProfileDropdown() {
  const navigate = useNavigate();
  const { currentUser, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onClick);
    return () => window.removeEventListener('mousedown', onClick);
  }, []);

  if (!currentUser) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-white border border-border hover:border-white/30 px-3 py-1.5 rounded-lg transition-all"
      >
        <span className="text-text-main font-medium">{currentUser.name}</span>
        <ChevronDown size={12} />
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-44 bg-slate-900 border border-border rounded-xl shadow-lg overflow-hidden z-50">
          <button
            onClick={() => { setOpen(false); navigate('/mypage'); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-text-main hover:bg-white/5 transition-colors"
          >
            <User size={13} /> 마이페이지
          </button>
          <button
            onClick={() => { setOpen(false); navigate('/project'); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-text-main hover:bg-white/5 transition-colors"
          >
            <LayoutDashboard size={13} /> 프로젝트
          </button>
          <button
            onClick={() => { setOpen(false); navigate('/pay'); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-text-main hover:bg-white/5 transition-colors"
          >
            <CreditCard size={13} /> 결제관리
          </button>
          {isAdmin(currentUser) && (
            <>
              <div className="h-px bg-border" />
              <button
                onClick={() => { setOpen(false); navigate('/admin'); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-amber-400 hover:bg-amber-500/10 transition-colors"
              >
                <ShieldCheck size={13} /> 관리자 페이지
              </button>
            </>
          )}
          <div className="h-px bg-border" />
          <button
            onClick={() => { setOpen(false); logout(); navigate('/login'); }}
            className="w-full flex items-center gap-2 px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut size={13} /> 로그아웃
          </button>
        </div>
      )}
    </div>
  );
}

export default function MainLayout() {
  const navigate = useNavigate();
  const { currentUser, login } = useAuth();
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="flex flex-col min-h-screen" style={{ background: 'var(--bg-base)' }}>
      <header className="flex items-center justify-between px-6 py-3 border-b border-border shrink-0 bg-[#070d1a] z-10 relative">
        <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
          <div className="bg-primary p-2 rounded-xl shadow-lg ring-2 ring-primary/20">
            <Box size={22} className="text-white" />
          </div>
          <h1 className="text-lg font-bold tracking-tight hero-gradient">LandUP</h1>
        </Link>
        <div className="flex items-center gap-2">
          <ActiveJobBadge />
          {currentUser ? (
            <ProfileDropdown />
          ) : (
            <>
              {import.meta.env.DEV && (
                <button
                  onClick={async () => {
                    if (USE_DIRECT) return;
                    try {
                      const res = await fetch(`${API_BASE}/auth/dev-login`, { method: 'POST', credentials: 'include' });
                      if (!res.ok) return;
                      const user = await res.json();
                      login(user);
                    } catch { /* 무시 */ }
                  }}
                  className="text-[10px] text-amber-400/40 hover:text-amber-300/70 border border-amber-500/15 hover:border-amber-400/30 px-2 py-1 rounded-lg transition-all"
                >
                  DEV
                </button>
              )}
              <button
                onClick={() => navigate('/login')}
                className="text-xs text-text-muted hover:text-white border border-border hover:border-white/30 px-3 py-1.5 rounded-lg transition-all"
              >
                로그인
              </button>
            </>
          )}
        </div>
      </header>

      <main className="flex-1 flex flex-col">
        <Outlet />
      </main>
      {isHome && <Footer />}
    </div>
  );
}
