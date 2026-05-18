/**
 * 레퍼런스 이미지 삭제 확인 모달.
 *
 * native confirm() 대체 — 체크박스 1개로 블랙리스트 동시 등록 여부 선택.
 * default: 블랙리스트 체크됨 (가장 흔한 케이스 = 품질 불량 영구 차단).
 *
 * 끄면: row 만 숨김. sha256 유효 — 다른 프로젝트에서 재다운로드 가능.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Trash2, X } from 'lucide-react';

interface Props {
  /** 표시용 sha256 prefix (12자 권장). */
  sha256Prefix: string;
  onConfirm: (blacklist: boolean) => void;
  onCancel: () => void;
}

export default function RefImageDeleteModal({ sha256Prefix, onConfirm, onCancel }: Props) {
  const [blacklist, setBlacklist] = useState(true);
  const confirmBtnRef = useRef<HTMLButtonElement | null>(null);

  // ESC 닫기 + body scroll lock + 자동 포커스
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    confirmBtnRef.current?.focus();
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onCancel]);

  const onBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onCancel();
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      onClick={onBackdropClick}
    >
      <div
        className="bg-slate-900 border border-border rounded-xl shadow-2xl max-w-md w-full overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-red-500/5">
          <div className="flex items-center gap-2 text-red-400">
            <Trash2 size={16} />
            <span className="text-sm font-bold">이미지 삭제</span>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-slate-400 hover:text-white transition-colors"
            aria-label="닫기"
          >
            <X size={16} />
          </button>
        </div>

        {/* 본문 */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-slate-200 leading-relaxed">
            이 이미지를 삭제하시겠습니까?
          </p>
          <p className="text-[11px] text-slate-500 font-mono">
            sha256: {sha256Prefix}…
          </p>

          {/* 블랙리스트 체크박스 */}
          <label className="flex items-start gap-2.5 pt-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={blacklist}
              onChange={(e) => setBlacklist(e.target.checked)}
              className="mt-0.5 w-4 h-4 accent-red-500 cursor-pointer"
            />
            <div className="flex-1">
              <div className="text-xs font-bold text-slate-200">
                블랙리스트에도 등록
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5 leading-relaxed">
                체크 시 이 sha256 은 DDG 재다운로드 시 영구 차단됩니다. 끄면 다른 프로젝트에서
                동일 이미지가 다시 다운로드될 수 있습니다.
              </div>
            </div>
          </label>
        </div>

        {/* 버튼 */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 bg-white/5 border-t border-border">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-1.5 text-xs font-bold text-slate-300 hover:bg-white/5 border border-border rounded-lg transition-colors"
          >
            취소
          </button>
          <button
            ref={confirmBtnRef}
            type="button"
            onClick={() => onConfirm(blacklist)}
            className="px-4 py-1.5 text-xs font-bold text-white bg-red-500 hover:bg-red-600 rounded-lg transition-colors"
          >
            삭제
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
