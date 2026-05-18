/**
 * tokenStorage — Access Token 메모리 저장소
 *
 * 왜 메모리?
 *  - sessionStorage/localStorage 에 저장하면 XSS로 탈취 가능.
 *  - 메모리는 JS 변수라 문서 DOM·쿠키 API로 접근 불가.
 *  - 새로고침 시 사라짐 — AuthContext 마운트 시 /auth/refresh 로 복원.
 */
let _token: string | null = null;

export const tokenStorage = {
  get: (): string | null => _token,
  set: (token: string | null): void => { _token = token; },
};
