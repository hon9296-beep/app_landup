/**
 * dev 전용 콘솔 로그 — prod 빌드에서 자동 제거 (vite tree-shake).
 * `import.meta.env.DEV` 가 prod 빌드 시 false 로 inline 되어 dead code 제거됨.
 *
 * 사용:
 *   import { debugLog } from '../lib/debug';
 *   debugLog({ event: 'object_click', id: ... });
 *
 * 2026-04-28 신설 (TR_D [Result_prod_디버그로그_노출] fix).
 *
 * 2026-05-08 추가 — DEBUG_FILTER 패턴.
 *   호출 위치는 23+군데 산재 (cleanup 하면 다른 디버깅 시 복원 부담).
 *   대신 콘솔 출력만 패턴 매칭으로 limit. null = 전체 출력 (default).
 *   원하는 카테고리만 보고 싶으면 정규식 박기. 예:
 *     const DEBUG_FILTER = /handlePlace|safety H/;  // 두 카테고리만
 *     const DEBUG_FILTER = null;                     // 전체 (default)
 */

// 현재 활성 필터 — 사용자가 원하는 카테고리 정규식. null 이면 전체 출력.
// 2026-05-08: handlePlace (자동 이동 fix 검증 중) 만 출력.
const DEBUG_FILTER: RegExp | null = /handlePlace/;

export const debugLog = (data: unknown): void => {
  if (!import.meta.env.DEV) return;
  const text = typeof data === 'string' ? data : JSON.stringify(data);
  if (DEBUG_FILTER && !DEBUG_FILTER.test(text)) return;
  console.log(text);
};
