/**
 * 프로젝트별 카드 그리드 묶음.
 *
 * 헤더 펼치기/접기 토글. 기본 펼침 (최신순).
 * 반응형 5~4 cols (모바일 미지원 전제 — 스타일 가이드 체크리스트).
 */
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { RefImageListItem, RefImageDetail, RefImageProjectGroup } from './types';
import RefImageCard from './RefImageCard';

interface Props {
  group: RefImageProjectGroup;
  open: boolean;
  onToggle: () => void;
  onEdit: (image: RefImageListItem) => void;
  onDelete: (image: RefImageListItem) => void;
  loadDetail: (id: number) => Promise<RefImageDetail>;
}

export default function RefImageProjectGroupView({
  group, open, onToggle, onEdit, onDelete, loadDetail,
}: Props) {
  return (
    <section className="border border-border rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 bg-white/5 hover:bg-white/10 transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          {open ? (
            <ChevronDown size={16} className="text-slate-400" />
          ) : (
            <ChevronRight size={16} className="text-slate-400" />
          )}
          <span className="text-sm font-bold text-white">{group.userProjectName}</span>
          {group.userProjectCreatedAt && (
            <span
              className="text-[11px] text-slate-400 font-mono"
              title={`프로젝트 #${group.userProjectId} · ${group.userProjectCreatedAt}`}
            >
              · {group.userProjectCreatedAt.replace('T', ' ').slice(0, 16)}
            </span>
          )}
          <span className="text-[11px] text-slate-500">{group.images.length}장</span>
        </div>
      </button>

      {open && (
        <div className="p-4 grid grid-cols-4 xl:grid-cols-5 gap-4">
          {group.images.map((img) => (
            <RefImageCard
              key={img.id}
              image={img}
              onEdit={onEdit}
              onDelete={onDelete}
              loadDetail={loadDetail}
            />
          ))}
        </div>
      )}
    </section>
  );
}
