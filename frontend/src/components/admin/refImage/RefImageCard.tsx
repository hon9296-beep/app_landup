/**
 * ref_image 개별 카드.
 *
 * 구성:
 *   - 세로로 살짝 긴 직사각형 썸네일 (aspect-[3/4])
 *   - s3Url null 이면 X 아이콘 placeholder
 *   - 하단 3 버튼: 수정 / 삭제 / 세부정보
 *
 * 세부정보 동작:
 *   - "세부정보" 버튼 = 토글 (open/close)
 *   - 썸네일 영역 내부에서 아래→위로 슬라이드업, 썸네일만 덮음 (버튼 행은 계속 보임)
 *   - 오버레이 내부 X 버튼으로도 닫기 가능
 *   - 여러 카드 동시 펼침 허용 (각 카드 자체 상태)
 *
 * 이벤트:
 *   onEdit      — 파일 교체 드래그앤드롭 모달 (추후)
 *   onDelete    — soft delete + blacklist
 *   loadDetail  — id → RefImageDetail (mock 은 동기, 추후 async API)
 */
import { useState } from 'react';
import { ImageOff, Pencil, Trash2, Info, X } from 'lucide-react';
import type { RefImageListItem, RefImageDetail, FloorSizeTier } from './types';
import RefImageLightbox from './RefImageLightbox';

const TIER_LABEL: Record<FloorSizeTier, string> = {
  small: '소형 (5~20평)',
  medium: '중형 (20~50평)',
  large: '대형 (50평~)',
  outdoor: '야외',
};

function formatFileSize(bytes: number | null): string {
  if (!bytes) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function extractHost(url: string | null): string {
  if (!url) return '-';
  if (url.startsWith('local://')) return '로컬 캐시';
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

interface Props {
  image: RefImageListItem;
  onEdit: (image: RefImageListItem) => void;
  onDelete: (image: RefImageListItem) => void;
  /** id → Detail. async API 호출 (Java GET /admin/ref-images/{id}). */
  loadDetail: (id: number) => Promise<RefImageDetail>;
}

export default function RefImageCard({ image, onEdit, onDelete, loadDetail }: Props) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<RefImageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  const toggleDetail = async () => {
    if (!open && !detail && !detailLoading) {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const d = await loadDetail(image.id);
        setDetail(d);
      } catch (e: unknown) {
        setDetailError(e instanceof Error ? e.message : '세부정보 로드 실패');
      } finally {
        setDetailLoading(false);
      }
    }
    setOpen((prev) => !prev);
  };

  return (
    <div className="bg-slate-800 border border-border rounded-xl overflow-hidden flex flex-col">
      {/* 썸네일 영역 — relative 로 오버레이 기준점 */}
      <div className="aspect-[3/4] bg-black/30 flex items-center justify-center overflow-hidden relative">
        {image.s3Url ? (
          <img
            src={image.s3Url}
            alt={`ref-${image.imageSha256.slice(0, 8)}`}
            className="w-full h-full object-cover cursor-zoom-in"
            loading="lazy"
            onClick={() => setLightboxOpen(true)}
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = 'none';
              const parent = (e.currentTarget as HTMLImageElement).parentElement;
              if (parent && !parent.querySelector('.fallback-icon')) {
                const div = document.createElement('div');
                div.className = 'fallback-icon flex flex-col items-center gap-1 text-slate-600';
                div.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="2" x2="2" y2="18"/><line x1="2" y1="2" x2="18" y2="18"/></svg>';
                parent.appendChild(div);
              }
            }}
          />
        ) : (
          <div className="flex flex-col items-center gap-1 text-slate-600">
            <ImageOff size={32} />
            <span className="text-[11px]">이미지 없음</span>
          </div>
        )}

        {/* 세부정보 슬라이드업 오버레이 — 썸네일 영역만 덮음 */}
        <div
          className={`absolute inset-0 bg-slate-900 transform transition-transform duration-300 ${
            open ? 'translate-y-0' : 'translate-y-full'
          } overflow-y-auto`}
        >
          <div className="p-3 space-y-2">
            <div className="flex items-center justify-between pb-2 border-b border-border">
              <span className="text-xs font-bold text-white">세부정보</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-slate-400 hover:text-white transition-colors"
                aria-label="세부정보 닫기"
              >
                <X size={13} />
              </button>
            </div>

            {detailLoading && (
              <div className="text-[11px] text-slate-400 text-center py-4">로딩 중...</div>
            )}
            {detailError && (
              <div className="text-[11px] text-red-400 text-center py-4">⚠ {detailError}</div>
            )}
            {detail && (
              <>
                <dl className="space-y-1.5">
                  <Field label="생성 프로젝트 명" value={detail.userProjectName ?? '(프로젝트 연결 없음)'} />
                  <Field label="카테고리" value={detail.brandCategoryNameKo ?? '-'} />
                  <Field label="도면 사이즈" value={TIER_LABEL[detail.floorSizeTier]} />
                  <Field label="LLM 검색어" value={detail.searchKeyword ?? '-'} />
                  <Field label="사이트" value={extractHost(detail.sourceUrl)} />
                  <Field label="참조 경로" value={detail.refPath ?? '-'} />
                  <Field label="파일 크기" value={formatFileSize(detail.fileSizeBytes)} />
                  <Field label="생성일" value={detail.createdAt ? detail.createdAt.replace('T', ' ').slice(0, 16) : '-'} />
                </dl>

                {(detail.isDeleted || detail.isBlacklisted) && (
                  <div className="p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-[10px] text-red-400 font-bold space-y-0.5">
                    {detail.isDeleted && <div>• 삭제 상태</div>}
                    {detail.isBlacklisted && <div>• 블랙리스트 — 재다운로드 차단</div>}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 버튼 3종 — 오버레이에 덮이지 않음 */}
      <div className="flex items-center border-t border-border">
        <button
          type="button"
          onClick={() => onEdit(image)}
          className="flex-1 py-2 text-xs font-bold text-slate-300 hover:bg-white/5 transition-colors flex items-center justify-center gap-1 border-r border-border"
          title="파일 교체"
        >
          <Pencil size={11} />
          수정
        </button>
        <button
          type="button"
          onClick={() => onDelete(image)}
          className="flex-1 py-2 text-xs font-bold text-red-400 hover:bg-red-500/10 transition-colors flex items-center justify-center gap-1 border-r border-border"
          title="삭제 + 블랙리스트 등록"
        >
          <Trash2 size={11} />
          삭제
        </button>
        <button
          type="button"
          onClick={toggleDetail}
          className={`flex-1 py-2 text-xs font-bold transition-colors flex items-center justify-center gap-1 ${
            open
              ? 'text-white bg-primary/20 hover:bg-primary/30'
              : 'text-primary hover:bg-white/5'
          }`}
          title={open ? '세부정보 닫기' : '세부정보 열기'}
        >
          <Info size={11} />
          세부정보
        </button>
      </div>

      {/* 라이트박스 — 썸네일 클릭 시 원본 확대/이동 */}
      {lightboxOpen && image.s3Url && (
        <RefImageLightbox
          src={image.s3Url}
          alt={`ref-${image.imageSha256.slice(0, 8)}`}
          onClose={() => setLightboxOpen(false)}
        />
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] text-slate-500 font-bold mb-0.5">{label}</dt>
      <dd className="text-[11px] text-white break-words leading-snug">{value}</dd>
    </div>
  );
}
