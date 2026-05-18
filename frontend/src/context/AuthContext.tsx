/**
 * AuthContext — 로그인 사용자 전역 상태 + JWT 관리
 *
 * 유저 정보: sessionStorage (새로고침 복원, 탭 종료 시 만료)
 * Access Token: tokenStorage (메모리) — 새로고침 시 /auth/refresh 로 자동 복원
 * Refresh Token: httpOnly 쿠키 (JS 접근 불가, XSS 방어)
 */
import axios from 'axios';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { tokenStorage } from '../lib/tokenStorage';
import { API_BASE, refreshAccessToken } from '../lib/axiosClient';
// [LOCAL_TEST_USE_DIRECT] Python 직통 모드 자동 로그인 (Java 미가동 환경 우회)
import { USE_DIRECT } from '../lib/api';

export interface AuthUser {
  id: number;
  name: string;
  email: string;
  membership: string;
  admin?: boolean;  // JSON 필드 "admin" (Java LoginResponse.isAdmin getter → Jackson 기본 변환)
}

/** login() 페이로드 — API 응답 그대로 받음.
 *  2026-05-10: Spring Boot Jackson SNAKE_CASE 적용으로 응답 키가 snake_case 로 옴 (예: access_token).
 *  과거 camelCase (accessToken) 와의 호환성을 위해 양쪽 키를 모두 옵셔널로 받음.
 *  login 함수 내부에서 fallback (accessToken ?? access_token) 처리. */
export interface LoginPayload extends AuthUser {
  accessToken?: string | null;
  access_token?: string | null;
  loginType?: string;
  login_type?: string;
  requiresVerification?: boolean;
  requires_verification?: boolean;
  requiresProfileCompletion?: boolean;
  requires_profile_completion?: boolean;
}

interface AuthContextType {
  currentUser: AuthUser | null;
  authLoading: boolean;
  login: (payload: LoginPayload) => void;
  logout: () => Promise<void>;
  updateUser: (partial: Partial<AuthUser>) => void;
}

const STORAGE_KEY = 'landup.user';

// ════════════════════════════════════════════════════════════════
// [LOCAL_TEST_USE_DIRECT] Python 직통 모드 더미 사용자 + 더미 토큰
// ────────────────────────────────────────────────────────────────
// Java 인증 없이 즉시 로그인 상태로 진입. 모든 API 호출은 더미 user_id=1
// 사용. axiosClient 가 토큰 헤더 첨부하지만 Java 백엔드 미가동이라 어차피
// axios 경로는 사용 불가 — 우리 USE_DIRECT 함수들 (fetch 직접 호출) 만 동작.
// ════════════════════════════════════════════════════════════════
const DEV_DIRECT_USER: AuthUser = {
  id: 1,
  name: 'Direct Dev',
  email: 'direct@local',
  membership: 'premium',
  admin: true,
};
const DEV_DIRECT_TOKEN = 'use-direct-dummy-token';

const AuthContext = createContext<AuthContextType | null>(null);

function readStored(): AuthUser | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed?.id === 'number' && typeof parsed?.email === 'string') {
      return parsed as AuthUser;
    }
    return null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // [LOCAL_TEST_USE_DIRECT] 직통 모드면 mount 시점부터 더미 user 로 시작
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() =>
    USE_DIRECT ? DEV_DIRECT_USER : readStored()
  );
  const [authLoading, setAuthLoading] = useState(() =>
    USE_DIRECT ? false : !!sessionStorage.getItem(STORAGE_KEY)
  );

  // 유저 정보를 sessionStorage 와 동기화
  useEffect(() => {
    if (currentUser) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(currentUser));
    } else {
      sessionStorage.removeItem(STORAGE_KEY);
    }
  }, [currentUser]);

  // 마운트 시 Access Token 자동 복원
  //   sessionStorage 에 유저 정보가 있으면 refreshToken 쿠키로 재발급 시도.
  //   쿠키도 만료/삭제됐으면 완전 로그아웃 처리.
  useEffect(() => {
    // [LOCAL_TEST_USE_DIRECT] 직통 모드: refresh API 호출 skip + 더미 토큰 세팅
    // Java 미가동 환경에서 ECONNREFUSED 가 콘솔 도배되는 문제 회피.
    if (USE_DIRECT) {
      tokenStorage.set(DEV_DIRECT_TOKEN);
      setAuthLoading(false);
      return;
    }
    if (!sessionStorage.getItem(STORAGE_KEY)) return;
    // axiosClient 의 공유 refreshAccessToken 사용 (TR_D [401_토큰_메모리휘발] 옵션 2 fix).
    // mount 시점 refresh promise 가 axiosClient request interceptor 와 공유되어,
    // 다른 컴포넌트의 API 호출이 이 promise 를 기다림 → 401 race 차단.
    refreshAccessToken()
      .then((token) => {
        if (!token) {
          sessionStorage.removeItem(STORAGE_KEY);
          setCurrentUser(null);
        }
        // 성공 시 refreshAccessToken 내부에서 tokenStorage.set 이미 호출
      })
      .finally(() => {
        setAuthLoading(false);
      });
  }, []);

  // axiosClient 의 refresh 실패 시 발행되는 이벤트 감지 → 자동 로그아웃
  useEffect(() => {
    const handler = () => {
      tokenStorage.set(null);
      setCurrentUser(null);
    };
    window.addEventListener('auth:logout', handler);
    return () => window.removeEventListener('auth:logout', handler);
  }, []);

  const login = (payload: LoginPayload) => {
    // 2026-05-10: Jackson SNAKE_CASE 적용 후 응답이 access_token / accessToken 모두 가능. fallback 처리.
    const token = payload.accessToken ?? payload.access_token;
    if (!token) return;  // 미인증 응답(토큰 없음)은 로그인 상태로 처리하지 않음
    tokenStorage.set(token);
    setCurrentUser({
      id: payload.id,
      name: payload.name,
      email: payload.email,
      membership: payload.membership,
      admin: payload.admin,
    });
  };

  const updateUser = (partial: Partial<AuthUser>) => {
    setCurrentUser(prev => prev ? { ...prev, ...partial } : prev);
  };

  const logout = async () => {
    // 서버에 refresh token 삭제 요청 (실패해도 클라이언트 상태는 초기화)
    await axios.post(`${API_BASE}/auth/logout`, {}, { withCredentials: true }).catch(() => {});
    tokenStorage.set(null);
    setCurrentUser(null);
  };

  return (
    <AuthContext.Provider value={{ currentUser, authLoading, login, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
