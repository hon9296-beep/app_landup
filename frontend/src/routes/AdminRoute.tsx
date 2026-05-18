/**
 * AdminRoute — 관리자 전용 라우트 가드
 *
 * 판정 기준: `users.is_admin` 컬럼 (LoginResponse.isAdmin → AuthUser.isAdmin)
 * dev-login 유저는 AuthService.getOrCreateDevUser 에서 isAdmin=true 로 생성됨.
 */
import { Navigate, useLocation, Outlet } from 'react-router-dom';
import { useAuth, type AuthUser } from '../context/AuthContext';

export function isAdmin(user: AuthUser | null | undefined): boolean {
  return !!user?.admin;
}

export default function AdminRoute() {
  const { currentUser } = useAuth();
  const location = useLocation();

  // 비로그인 → /login
  if (!currentUser) {
    const redirect = location.pathname + location.search;
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }

  // 로그인했지만 admin 아니면 → /
  if (!isAdmin(currentUser)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
