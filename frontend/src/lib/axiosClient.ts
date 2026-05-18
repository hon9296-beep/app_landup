/**
 * axiosClient — JWT 인증 자동 처리 + 401 auto refresh
 *
 * 설정:
 *  - baseURL: '/api'
 *  - withCredentials: true  (refreshToken httpOnly 쿠키 전송)
 *
 * 인터셉터:
 *  - 요청: tokenStorage.get() 으로 Authorization: Bearer <JWT> 헤더 자동 첨부
 *  - 응답: 401 Unauthorized → /auth/refresh 호출 → 새 토큰 받고 원본 요청 재시도
 *          refresh 실패 → tokenStorage 클리어 + 'auth:logout' 이벤트 발행
 *
 * 사용:
 *   import axiosClient from './axiosClient';
 *   const res = await axiosClient.post('/detect', formData);
 *   const data = res.data;
 */
import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { tokenStorage } from './tokenStorage';

// VITE_API_URL 있으면 절대 URL, 없으면 기존 상대 경로 (로컬 dev 호환)
export const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api`
  : '/api';

const axiosClient = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

// ── 응답 인터셉터: 401 → /auth/refresh 자동 재시도 ──────
interface RetryConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

// 동시 401 여러 건이 와도 refresh 는 한 번만 돌게 큐잉.
// AuthContext 와 공유 — mount 시점 refresh + 401 인터셉터 refresh 가 같은 promise 기다림.
// 2026-04-28 추가: 401 race 근본 fix (TR_D [401_토큰_메모리휘발] 옵션 2).
let refreshPromise: Promise<string | null> | null = null;

export async function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true })
      .then((res) => {
        // 2026-05-10: Spring Boot Jackson SNAKE_CASE 적용 후 access_token. 양쪽 fallback.
        const newToken = (res.data.accessToken ?? res.data.access_token) as string;
        tokenStorage.set(newToken);
        return newToken;
      })
      .catch(() => {
        // refresh 실패 시 null 반환 (호출자가 처리). 토큰은 안 비움 (caller 책임).
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

// ── 요청 인터셉터: Authorization 헤더 자동 첨부 ──────────
// 토큰 없는데 refreshPromise 진행 중이면 기다림 → 401 race 차단.
axiosClient.interceptors.request.use(async (config) => {
  let token = tokenStorage.get();
  if (!token && refreshPromise) {
    // AuthContext mount 시점 refresh 진행 중 → 끝날 때까지 대기 후 재조회
    token = await refreshPromise;
  }
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

axiosClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetryConfig | undefined;

    // 401/403 이 아니거나 설정 없음 → 그대로 reject
    // Spring Security가 만료 토큰에 대해 403을 반환하는 경우도 refresh 시도
    const status = error.response?.status;
    if (!originalRequest || (status !== 401 && status !== 403)) {
      return Promise.reject(error);
    }

    // /auth/refresh 자체에서 401 → 무한 루프 방지
    if (originalRequest.url?.includes('/auth/refresh')) {
      tokenStorage.set(null);
      window.dispatchEvent(new Event('auth:logout'));
      return Promise.reject(error);
    }

    // 이미 재시도 한 요청이 또 401/403 → 포기
    if (originalRequest._retry) {
      // 재시도 후에도 403 → 실제 권한 없음 (토큰 만료 아님) — 로그아웃 안 함
      if (status === 403) {
        return Promise.reject(error);
      }
      tokenStorage.set(null);
      window.dispatchEvent(new Event('auth:logout'));
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    try {
      const newToken = await refreshAccessToken();
      if (!newToken) {
        // refresh 실패 (refreshAccessToken 가 null 반환) → 로그아웃
        tokenStorage.set(null);
        window.dispatchEvent(new Event('auth:logout'));
        return Promise.reject(error);
      }
      // 새 토큰으로 원본 요청 재시도
      if (originalRequest.headers) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`;
      }
      return axiosClient(originalRequest);
    } catch (refreshError) {
      tokenStorage.set(null);
      window.dispatchEvent(new Event('auth:logout'));
      return Promise.reject(refreshError);
    }
  },
);

export default axiosClient;
