/**
 * Admin RefImage API 클라이언트 — Java 백엔드 호출.
 *
 * 엔드포인트 (context-path '/api' 자동):
 *   GET    /admin/ref-images?categoryId=&tier=&from=&to=&page=&size=  → Page<RefImageListItem>
 *   GET    /admin/ref-images/{id}                                       → RefImageDetail
 *   PUT    /admin/ref-images/{id}/replace  (multipart, field 'file')   → RefImage
 *   DELETE /admin/ref-images/{id}  (X-Admin-Id 헤더)                    → 204
 *   GET    /brand-categories                                            → BrandCategory[]
 */
import axiosClient from './axiosClient';

// ── 타입 (Java DTO 1:1 매칭) ─────────────────────────────────────

export type FloorSizeTier = 'small' | 'medium' | 'large' | 'outdoor';

export interface BrandCategory {
  id: number;
  code: string;
  nameKo: string;
  folderName: string;
  isActive: boolean;
}

export interface RefImageListItem {
  id: number;
  userProjectId: number | null;
  userProjectName: string | null;        // user_projects.name. 같은 이름 중복 가능 — created_at 으로 구분
  userProjectCreatedAt: string | null;   // user_projects.created_at. 동일명 disambiguation
  imageSha256: string;
  s3Url: string | null;
  filePath: string | null;
  floorSizeTier: FloorSizeTier;
  createdAt: string | null;
}

export interface RefImageDetail {
  id: number;
  userProjectId: number | null;
  userProjectName: string | null;
  brandCategoryId: number;
  brandCategoryNameKo: string | null;
  floorSizeTier: FloorSizeTier;
  searchKeyword: string | null;
  sourceUrl: string | null;
  s3Url: string | null;
  filePath: string | null;
  fileSizeBytes: number | null;
  refPath: string | null;
  createdAt: string | null;
  isDeleted: boolean;
  isBlacklisted: boolean;
}

export interface PageResponse<T> {
  content: T[];
  totalElements: number;
  totalPages: number;
  number: number;       // current page (0-indexed)
  size: number;
  first: boolean;
  last: boolean;
}

// ── API 함수 ────────────────────────────────────────────────────

export async function listRefImages(params: {
  categoryId?: number;
  tier?: FloorSizeTier;
  from?: string;   // ISO datetime
  to?: string;
  page?: number;
  size?: number;
}): Promise<PageResponse<RefImageListItem>> {
  const res = await axiosClient.get<PageResponse<RefImageListItem>>('/admin/ref-images', {
    params: {
      ...(params.categoryId != null && { categoryId: params.categoryId }),
      ...(params.tier && { tier: params.tier }),
      ...(params.from && { from: params.from }),
      ...(params.to && { to: params.to }),
      page: params.page ?? 0,
      size: params.size ?? 10,
    },
  });
  return res.data;
}

export async function getRefImageDetail(id: number): Promise<RefImageDetail> {
  const res = await axiosClient.get<RefImageDetail>(`/admin/ref-images/${id}`);
  return res.data;
}

/**
 * 파일 교체 (수정). 서버에서 SHA256 자체 계산, 디스크 저장.
 * 허용 확장자: jpg/jpeg/png/webp. 최대 10MB.
 */
export async function replaceRefImageFile(id: number, file: File): Promise<RefImageListItem> {
  const form = new FormData();
  form.append('file', file);
  const res = await axiosClient.put<RefImageListItem>(`/admin/ref-images/${id}/replace`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

/**
 * 삭제 (soft delete). blacklist=true (default) 면 sha256 영구 차단까지 동시 적용.
 * blacklist=false 면 row 만 숨기고 sha256 은 유효 (다른 프로젝트에서 재사용 가능).
 * adminUserId 는 X-Admin-Id 헤더로 전달.
 */
export async function deleteRefImage(
  id: number,
  adminUserId?: number,
  blacklist: boolean = true,
): Promise<void> {
  await axiosClient.delete(`/admin/ref-images/${id}`, {
    params: { blacklist },
    headers: adminUserId != null ? { 'X-Admin-Id': String(adminUserId) } : undefined,
  });
}

export async function listBrandCategories(): Promise<BrandCategory[]> {
  const res = await axiosClient.get<BrandCategory[]>('/brand-categories');
  return res.data;
}
