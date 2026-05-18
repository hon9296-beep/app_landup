/**
 * ref_image 관리자 UI 타입 — `lib/refImageApi.ts` 가 단일 소스. 본 파일은 re-export.
 *
 * 이전엔 mock 단계라 자체 정의했지만, 실 API 연동 시 lib 쪽으로 통합.
 * RefImageProjectGroup 만 UI 전용으로 자체 정의.
 */
export type {
  FloorSizeTier,
  RefImageListItem,
  RefImageDetail,
  BrandCategory,
} from '../../../lib/refImageApi';

import type { RefImageListItem } from '../../../lib/refImageApi';

/**
 * 프론트 전용 — 프로젝트별로 이미지 묶기 (UI 렌더링용).
 *
 * 같은 이름 중복 허용 정책: 동일 (userProjectId) 만 묶음. 동일 name+다른 id 는 별도 그룹.
 * 헤더 표시는 name + createdAt 함께 — 동일명 그룹들이 시간으로 구분되도록.
 */
export interface RefImageProjectGroup {
  userProjectId: number | null;
  userProjectName: string;          // "(프로젝트 연결 없음)" fallback 포함
  userProjectCreatedAt: string | null;
  images: RefImageListItem[];
}
