/**
 * AppRoutes — 라우트 선언
 *
 * Layout 구조:
 * - MainLayout: 헤더 포함 (/, /project/*, /mypage, /pay, /admin)
 * - AuthLayout: 좌상단 "← 홈으로"만 (/login, /signup, /naver/callback, /kakao/callback)
 *
 * 가드 구조:
 * - ProtectedRoute: 로그인 필수 (/project/*, /mypage, /pay)
 * - AdminRoute: admin 이메일 화이트리스트 (/admin)
 */
import { useState, useEffect } from 'react';
import { Routes, Route, useNavigate, useSearchParams, useLocation, Navigate } from 'react-router-dom';
import Login from './components/Login';
import SignUp from './components/SignUp';
import NaverCallback from './components/NaverCallback';
import KakaoCallback from './components/KakaoCallback';
import KakaoProfileCompletion from './components/KakaoProfileCompletion';
import EmailVerificationCallback from './components/EmailVerificationCallback';
import GoogleCallback from './components/GoogleCallback';
import AdminPanel from './components/AdminPanel';
import AdminUserPage from './pages/admin/AdminUserPage';
import AdminReferencePage from './pages/admin/AdminReferencePage';
import HomePage from './pages/HomePage';
import MyPage from './pages/MyPage';
import PayPage from './pages/PayPage';
import PaySuccessPage from './pages/PaySuccessPage';
import PayFailPage from './pages/PayFailPage';
import ProjectHubPage from './pages/project/ProjectHubPage';
import NewProjectPage from './pages/project/NewProjectPage';
import FloorPage from './pages/project/FloorPage';
import ResultPage from './pages/project/ResultPage';
import ProjectResolver from './pages/project/ProjectResolver';
import AnalysisReportPreview from './pages/AnalysisReportPreview';
import MainLayout from './layouts/MainLayout';
// NoFooterLayout 폐기 (2026-05-08) — MainLayout 의 isHome 분기로 footer 표시 통일.
import AuthLayout from './layouts/AuthLayout';
import ProtectedRoute from './routes/ProtectedRoute';
import AdminRoute from './routes/AdminRoute';
import { useAuth } from './context/AuthContext';

function LoginRoute() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { login } = useAuth();
  const redirect = params.get('redirect') || '/';
  return (
    <Login
      onSuccess={(user) => { login(user); navigate(redirect, { replace: true }); }}
      onVerificationRequired={(email) => navigate('/auth/email-sent', { state: { email }, replace: true })}
      onSignUpClick={() => navigate('/signup')}
    />
  );
}

function SignUpRoute() {
  const navigate = useNavigate();
  return (
    <SignUp
      onSuccess={(email) => navigate('/auth/email-sent', { state: { email }, replace: true })}
      onLoginClick={() => navigate('/login')}
    />
  );
}

function NaverCallbackRoute() {
  const navigate = useNavigate();
  const { login } = useAuth();
  return (
    <NaverCallback
      onSuccess={(user) => { login(user); navigate('/', { replace: true }); }}
      onVerificationRequired={(user) => {
        navigate('/auth/email-sent', { state: { email: user.email }, replace: true });
      }}
      onError={() => navigate('/login')}
    />
  );
}

function KakaoCallbackRoute() {
  const navigate = useNavigate();
  const { login } = useAuth();
  return (
    <KakaoCallback
      onSuccess={(user) => { login(user); navigate('/', { replace: true }); }}
      // 프로필 미완성 — JWT 없음, 상태로 userId 전달 (login() 호출 안 함)
      onProfileRequired={(user) => {
        navigate('/kakao/profile', { state: { pendingUser: user }, replace: true });
      }}
      // 프로필은 있으나 이메일 미인증
      onVerificationRequired={(user) => {
        navigate('/auth/email-sent', { state: { email: user.email }, replace: true });
      }}
      onError={() => navigate('/login')}
    />
  );
}

function KakaoProfileRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const pendingUser = (location.state as { pendingUser?: { id: number; name: string; email: string; profileToken?: string } } | null)?.pendingUser;

  if (!pendingUser) return <Navigate to="/login" replace />;

  return (
    <KakaoProfileCompletion
      userId={pendingUser.id}
      profileToken={pendingUser.profileToken}
      initialName={pendingUser.name}
      initialEmail={pendingUser.email}
      onSuccess={(updated) => {
        if (updated.requiresVerification) {
          navigate('/auth/email-sent', { state: { email: updated.email }, replace: true });
        } else {
          login(updated);
          navigate('/', { replace: true });
        }
      }}
      onError={() => navigate('/login')}
    />
  );
}

function GoogleCallbackRoute() {
  const navigate = useNavigate();
  const { login } = useAuth();
  return (
    <GoogleCallback
      onSuccess={(user) => { login(user); navigate('/', { replace: true }); }}
      onVerificationRequired={(user) => {
        navigate('/auth/email-sent', { state: { email: user.email }, replace: true });
      }}
      onError={() => navigate('/login')}
    />
  );
}

// ── 공통 이메일 발송 안내 화면 (/auth/email-sent) ──────────────────────────
// 카카오/네이버/구글 모두 이 라우트로 이동. location.state.email 로 이메일 수신.
// 다른 탭에서 인증 완료 시 localStorage 'landup_verified' 이벤트로 자동 로그인.
function EmailSentRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();
  const [verified, setVerified] = useState(false);

  const email = (location.state as { email?: string } | null)?.email ?? '';

  if (!email) return <Navigate to="/login" replace />;

  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'landup_verified' && e.newValue) {
        try {
          const result = JSON.parse(e.newValue);
          localStorage.removeItem('landup_verified');
          setVerified(true);
          setTimeout(() => { login(result); navigate('/', { replace: true }); }, 800);
        } catch { /* 파싱 오류 무시 */ }
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  if (verified) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8">
            <div className="w-12 h-12 rounded-full bg-green-900/40 border border-green-800/50 flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-white mb-2">인증이 완료되었습니다!</h2>
            <p className="text-slate-400 text-sm">잠시 후 이동합니다...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">LandUP</h1>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8 text-center">
          <div className="w-12 h-12 rounded-full bg-indigo-900/40 border border-indigo-800/50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-white mb-2">이메일을 확인해주세요</h2>
          <p className="text-slate-400 text-sm mb-1">
            <span className="text-indigo-400 font-medium">{email}</span>으로
          </p>
          <p className="text-slate-400 text-sm mb-4">인증 메일을 발송했습니다.</p>
          <p className="text-slate-500 text-xs mb-6">
            메일의 인증 링크를 클릭하면 가입이 완료됩니다.<br />
            메일이 오지 않으면 스팸함을 확인해주세요.
          </p>
          <button
            onClick={() => navigate('/login', { replace: true })}
            className="text-indigo-400 text-sm hover:text-indigo-300 transition"
          >
            로그인 페이지로 이동
          </button>
        </div>
      </div>
    </div>
  );
}

function EmailVerificationRoute() {
  const navigate = useNavigate();
  const { login } = useAuth();
  return (
    <EmailVerificationCallback
      onSuccess={(user) => { login(user); navigate('/', { replace: true }); }}
      onError={() => navigate('/login')}
    />
  );
}

function AdminPanelRoute() {
  const navigate = useNavigate();
  return <AdminPanel onBack={() => navigate('/')} />;
}

export default function AppRoutes() {
  return (
    <Routes>
      {/* 인증 화면 (AuthLayout) */}
      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/signup" element={<SignUpRoute />} />
        <Route path="/naver/callback" element={<NaverCallbackRoute />} />
        <Route path="/kakao/callback" element={<KakaoCallbackRoute />} />
        <Route path="/kakao/profile" element={<KakaoProfileRoute />} />
        <Route path="/google/callback" element={<GoogleCallbackRoute />} />
        <Route path="/auth/verify" element={<EmailVerificationRoute />} />
        <Route path="/auth/email-sent" element={<EmailSentRoute />} />
      </Route>

      {/* 메인 (MainLayout — 헤더 + 푸터) */}
      <Route element={<MainLayout />}>
        {/* 누구나 접근 */}
        <Route path="/" element={<HomePage />} />

        {/* 로그인 필수 */}
        <Route element={<ProtectedRoute />}>
          <Route path="/project/floor" element={<FloorPage />} />
          <Route path="/mypage" element={<MyPage />} />
          {/* [DEV PREVIEW] AnalysisReport 렌더 확인용. 대시보드 완성 후 본 라우트 + AnalysisReportPreview.tsx 제거 */}
          <Route path="/report-preview" element={<AnalysisReportPreview />} />
          <Route path="/pay" element={<PayPage />} />
          <Route path="/pay/success" element={<PaySuccessPage />} />
          <Route path="/pay/fail" element={<PayFailPage />} />
        </Route>

        {/* Admin 전용 */}
        <Route element={<AdminRoute />}>
          <Route path="/admin" element={<AdminPanelRoute />} />
          <Route path="/admin/user" element={<AdminUserPage />} />
          <Route path="/admin/reference" element={<AdminReferencePage />} />
        </Route>

        {/* 구 경로 호환 */}
        <Route path="/app" element={<Navigate to="/project/new" replace />} />
      </Route>

      {/* 프로젝트 작업 화면 — MainLayout 으로 통일 (2026-05-08).
          푸터는 MainLayout 안 isHome 분기라 /project/* 에선 자동 비표시 (홈에서만 노출). */}
      <Route element={<MainLayout />}>
        <Route element={<ProtectedRoute />}>
          <Route path="/project" element={<ProjectHubPage />} />
          <Route path="/project/new" element={<NewProjectPage />} />
          <Route path="/project/result" element={<ResultPage />} />
          {/* deep link: /project/41 같은 직접 접근 → fetch 후 stage 따라 redirect */}
          <Route path="/project/:id" element={<ProjectResolver />} />
        </Route>
      </Route>

      {/* 그 외 전부 / 로 */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
