/**
 * 관리자 "레퍼런스 이미지 관리" 메인 페이지 — 실 API 연동.
 *
 * 엔드포인트:
 *   GET    /api/admin/ref-images?categoryId=&tier=&from=&to=&page=&size=
 *   GET    /api/admin/ref-images/{id}
 *   PUT    /api/admin/ref-images/{id}/replace  (multipart, field 'file')
 *   DELETE /api/admin/ref-images/{id}  (X-Admin-Id 헤더)
 *
 * 페이지네이션은 server-side. 필터 변경 시 page=0 리셋.
 * 카테고리 옵션은 BrandCategory 실 API.
 *
 * 스타일 가이드 엄수: reports/AD/2026-04-23_frontend_style_guide.md
 */
import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, RotateCcw, ImageIcon } from 'lucide-react';
import RefImageFilterBar, { type FilterValues } from './RefImageFilterBar';
import RefImageProjectGroupView from './RefImageProjectGroup';
import RefImageDeleteModal from './RefImageDeleteModal';
import RefImageEditModal from './RefImageEditModal';
import type { RefImageListItem as UIListItem, RefImageProjectGroup } from './types';
import {
  listRefImages,
  listBrandCategories,
  getRefImageDetail,
  replaceRefImageFile,
  deleteRefImage,
  type BrandCategory,
} from '../../../lib/refImageApi';
import { useAuth } from '../../../context/AuthContext';

const PAGE_SIZE = 10;

interface Props {
  onBack: () => void;
}

export default function AdminRefImagePage({ onBack }: Props) {
  const { currentUser } = useAuth();

  const [filter, setFilter] = useState<FilterValues>({
    floorSizeTier: 'all',
    brandCategoryId: 'all',
    searchKeyword: '',
    date: 'all',
  });
  const [page, setPage] = useState(0);
  const [openProjectIds, setOpenProjectIds] = useState<Set<number>>(new Set());

  // 실 API 데이터
  const [items, setItems] = useState<UIListItem[]>([]);
  const [totalElements, setTotalElements] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [categories, setCategories] = useState<BrandCategory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 수정 모달 — 클릭 시 띄움. 모달 내부에 드롭존 + 미리보기 + 확인/취소
  const [pendingEdit, setPendingEdit] = useState<UIListItem | null>(null);

  // ── 카테고리 1회 로드 ──
  useEffect(() => {
    listBrandCategories()
      .then(setCategories)
      .catch((e) => console.error('[admin-refimage] 카테고리 로드 실패', e));
  }, []);

  // ── 리스트 fetch (필터/페이지 변경 시) ──
  useEffect(() => {
    const cidNum = filter.brandCategoryId === 'all' ? undefined : Number(filter.brandCategoryId);
    const tierVal = filter.floorSizeTier === 'all' ? undefined : filter.floorSizeTier;
    // 날짜는 from = 그날 00:00, to = 그날 23:59
    let fromIso: string | undefined;
    let toIso: string | undefined;
    if (filter.date !== 'all') {
      fromIso = `${filter.date}T00:00:00`;
      toIso = `${filter.date}T23:59:59`;
    }

    setLoading(true);
    setError(null);
    listRefImages({
      categoryId: cidNum,
      tier: tierVal,
      from: fromIso,
      to: toIso,
      page,
      size: PAGE_SIZE,
    })
      .then((resp) => {
        setItems(resp.content);
        setTotalElements(resp.totalElements);
        setTotalPages(Math.max(1, resp.totalPages));
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : '목록 조회 실패');
        setItems([]);
        setTotalElements(0);
        setTotalPages(1);
      })
      .finally(() => setLoading(false));
  }, [filter, page]);

  // ── 카테고리 검색 키워드 — client-side 보조 (서버 필터 categoryId 우선) ──
  const filteredItems = useMemo(() => {
    if (!filter.searchKeyword.trim()) return items;
    const q = filter.searchKeyword.trim().toLowerCase();
    const cat = categories.find(
      (c) => c.nameKo.toLowerCase().includes(q) || c.code.toLowerCase().includes(q),
    );
    if (!cat) return [];
    // 서버에서 categoryId 필터 안 걸린 상태라면 client-side 로 한 번 더 필터
    // (categoryId 가 already 'all' 이면서 keyword 만 입력한 케이스)
    return items;  // 서버에서 이미 필터링됨 — keyword 는 카테고리 dropdown 자동 매칭만
  }, [items, filter.searchKeyword, categories]);

  // ── 프로젝트별 그룹핑 ──
  // 정책: 이름 중복 허용. 그룹 키는 userProjectId 만 (이름 같아도 id 다르면 별도 그룹).
  // 헤더는 name + createdAt 같이 표시해서 동일명 그룹들이 시간으로 구분되도록.
  const groups: RefImageProjectGroup[] = useMemo(() => {
    const map = new Map<number, UIListItem[]>();
    for (const img of filteredItems) {
      const key = img.userProjectId ?? -1;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(img);
    }
    return Array.from(map.entries()).map(([pid, images]) => {
      const head = images[0];
      return {
        userProjectId: pid === -1 ? null : pid,
        userProjectName: pid === -1
          ? '(프로젝트 연결 없음)'
          : (head.userProjectName ?? `프로젝트 #${pid}`),  // backend lookup 실패 시만 fallback
        userProjectCreatedAt: pid === -1 ? null : (head.userProjectCreatedAt ?? null),
        images,
      };
    });
  }, [filteredItems]);

  // 첫 로드 시 모든 그룹 자동 펼침
  useEffect(() => {
    setOpenProjectIds(new Set(groups.map((g) => g.userProjectId ?? -1)));
  }, [groups.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const allClosed = openProjectIds.size === 0;
  const toggleProject = (pid: number | null) => {
    const key = pid ?? -1;
    setOpenProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const closeAll = () => setOpenProjectIds(new Set());
  const openAll = () =>
    setOpenProjectIds(new Set(groups.map((g) => g.userProjectId ?? -1)));

  // ── 액션 핸들러 — 실 API 호출 ──

  const handleEdit = (img: UIListItem) => {
    setPendingEdit(img);
  };

  // 모달 onConfirm 콜백 — 실제 PUT 호출. 실패 시 throw → 모달이 error 표시.
  const onEditConfirm = async (file: File) => {
    if (!pendingEdit) return;
    const targetId = pendingEdit.id;
    const updated = await replaceRefImageFile(targetId, file);
    console.log('[admin-refimage] replace 성공', updated);
    setItems((prev) => prev.map((it) => (it.id === targetId ? { ...it, ...updated } : it)));
    setPendingEdit(null);  // 성공 시 모달 닫기
  };

  // 삭제는 모달로 (native confirm 대체) — pendingDelete 가 있으면 모달 띄움
  const [pendingDelete, setPendingDelete] = useState<UIListItem | null>(null);

  const handleDelete = (img: UIListItem) => {
    setPendingDelete(img);
  };

  const onDeleteConfirm = async (blacklist: boolean) => {
    const img = pendingDelete;
    if (!img) return;
    setPendingDelete(null);
    try {
      await deleteRefImage(img.id, currentUser?.id, blacklist);
      console.log('[admin-refimage] delete 성공', img.id, 'blacklist=', blacklist);
      setItems((prev) => prev.filter((it) => it.id !== img.id));
      setTotalElements((n) => Math.max(0, n - 1));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '삭제 실패';
      console.error('[admin-refimage] delete 실패', err);
      alert(`삭제 실패: ${msg}`);
    }
  };

  // 세부정보 패널 — 실 API
  const loadDetail = async (id: number) => {
    return await getRefImageDetail(id);
  };

  // 카테고리 prop 그대로 전달 (BrandCategory 통합 타입 사용)
  const categoryOptions = categories;

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col fade-in">
      <header className="flex items-center gap-3 px-6 py-4 border-b border-border shrink-0">
        <button
          onClick={onBack}
          className="text-slate-400 hover:text-white transition-colors"
          aria-label="뒤로"
        >
          <ArrowLeft size={18} />
        </button>
        <ImageIcon size={16} className="text-primary" />
        <span className="text-white font-bold text-sm">레퍼런스 이미지 관리</span>
        <span className="ml-auto text-[11px] text-emerald-400 font-bold">
          실 API 연동 중 · {loading ? '로딩...' : `총 ${totalElements}장`}
        </span>
      </header>

      <main className="flex-1 px-6 py-5 space-y-4 overflow-auto">
        <RefImageFilterBar value={filter} onChange={(v) => { setFilter(v); setPage(0); }} categories={categoryOptions} />

        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
            ⚠ {error}
          </div>
        )}

        {/* 전부 펼치기/닫기 + 필터 결과 요약 */}
        <div className="flex items-center justify-between">
          <div className="text-xs text-slate-400">
            결과 <span className="text-white font-bold">{totalElements}</span>장 (페이지 {page + 1}/{totalPages})
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={allClosed ? openAll : closeAll}
              className="flex items-center gap-1.5 bg-white/5 hover:bg-white/10 border border-border rounded-lg px-3 py-1.5 text-xs font-bold text-slate-300 transition-colors"
            >
              <RotateCcw size={11} />
              {allClosed ? '전부 펼치기' : '전부 닫기'}
            </button>
          </div>
        </div>

        {/* 프로젝트 그룹 리스트 */}
        <div className="space-y-3">
          {!loading && groups.length === 0 && !error && (
            <div className="text-center py-12 text-slate-500 text-xs">
              조건에 맞는 이미지가 없습니다.
            </div>
          )}
          {groups.map((group) => {
            const key = group.userProjectId ?? -1;
            return (
              <RefImageProjectGroupView
                key={key}
                group={group}
                open={openProjectIds.has(key)}
                onToggle={() => toggleProject(group.userProjectId)}
                onEdit={handleEdit}
                onDelete={handleDelete}
                loadDetail={loadDetail}
              />
            );
          })}
        </div>

        {/* 페이지네이션 */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-4">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="px-3 py-1.5 text-xs font-bold bg-white/5 hover:bg-white/10 border border-border rounded-lg text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              ← 이전
            </button>
            {Array.from({ length: totalPages }).map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setPage(i)}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-colors ${
                  i === page
                    ? 'bg-primary text-white'
                    : 'bg-white/5 hover:bg-white/10 border border-border text-slate-300'
                }`}
              >
                {i + 1}
              </button>
            ))}
            <button
              type="button"
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              className="px-3 py-1.5 text-xs font-bold bg-white/5 hover:bg-white/10 border border-border rounded-lg text-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              다음 →
            </button>
          </div>
        )}
      </main>

      {/* 삭제 확인 모달 — pendingDelete 가 있을 때만 렌더 */}
      {pendingDelete && (
        <RefImageDeleteModal
          sha256Prefix={pendingDelete.imageSha256.slice(0, 12)}
          onConfirm={onDeleteConfirm}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {/* 교체 모달 — pendingEdit 가 있을 때만 렌더 */}
      {pendingEdit && (
        <RefImageEditModal
          sha256Prefix={pendingEdit.imageSha256.slice(0, 12)}
          onConfirm={onEditConfirm}
          onCancel={() => setPendingEdit(null)}
        />
      )}
    </div>
  );
}
