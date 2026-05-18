/**
 * 레퍼런스 이미지 파일 교체 모달.
 *
 * 흐름: 드롭/선택 → 미리보기 → 확인/취소 → 확인 시에만 API 호출.
 * 취소 경로: ESC / X 버튼 / 취소 버튼 / 배경 클릭 (제출 전이라 무해).
 *
 * 검증: jpg/jpeg/png/webp, 최대 10MB. Java RefImageService 기준과 일치.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Pencil, X, Upload, FileImage } from 'lucide-react';

interface Props {
  /** 교체 대상 sha256 prefix (12자) — 헤더에 표시. */
  sha256Prefix: string;
  onConfirm: (file: File) => Promise<void> | void;
  onCancel: () => void;
}

const ALLOWED_EXTS = ['jpg', 'jpeg', 'png', 'webp'];
const MAX_BYTES = 10 * 1024 * 1024;  // 10MB

export default function RefImageEditModal({ sha256Prefix, onConfirm, onCancel }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // ESC 닫기 + body scroll lock
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onCancel();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onCancel, submitting]);

  // 미리보기 URL — file 변경 시 생성, unmount/교체 시 revoke (메모리 누수 방지)
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const validateAndSet = (f: File) => {
    setError(null);
    const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
    if (!ALLOWED_EXTS.includes(ext)) {
      setError(`지원하지 않는 확장자: .${ext} (허용: ${ALLOWED_EXTS.join(', ')})`);
      return;
    }
    if (f.size > MAX_BYTES) {
      setError(`파일 크기 초과: ${(f.size / 1024 / 1024).toFixed(2)}MB (최대 10MB)`);
      return;
    }
    setFile(f);
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) validateAndSet(f);
  };

  const onPickClick = () => fileInputRef.current?.click();
  const onPickChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = '';  // 같은 파일 재선택 가능하게
    if (f) validateAndSet(f);
  };

  const onSubmit = async () => {
    if (!file || submitting) return;
    setSubmitting(true);
    try {
      await onConfirm(file);
      // 부모가 모달 닫음 (API 성공 후 state 업데이트)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '교체 실패';
      setError(msg);
      setSubmitting(false);
    }
  };

  const onBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !submitting) onCancel();
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
      onClick={onBackdropClick}
    >
      <div
        className="bg-slate-900 border border-border rounded-xl shadow-2xl max-w-lg w-full overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-primary/5">
          <div className="flex items-center gap-2 text-primary">
            <Pencil size={16} />
            <span className="text-sm font-bold">이미지 교체</span>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="text-slate-400 hover:text-white transition-colors disabled:opacity-30"
            aria-label="닫기"
          >
            <X size={16} />
          </button>
        </div>

        {/* 본문 */}
        <div className="px-5 py-4 space-y-3">
          <p className="text-[11px] text-slate-500 font-mono">
            기존 sha256: {sha256Prefix}…
          </p>

          {/* 드롭존 */}
          <div
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            onClick={onPickClick}
            className={`
              border-2 border-dashed rounded-xl p-6 transition-colors cursor-pointer
              ${dragOver ? 'border-primary bg-primary/10' : 'border-border bg-white/5 hover:bg-white/10'}
            `}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={onPickChange}
              className="hidden"
            />
            {file && previewUrl ? (
              <div className="flex items-start gap-3">
                <img
                  src={previewUrl}
                  alt="preview"
                  className="w-20 h-24 object-cover rounded-lg border border-border"
                />
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-1.5 text-primary">
                    <FileImage size={12} />
                    <span className="text-xs font-bold truncate">{file.name}</span>
                  </div>
                  <div className="text-[11px] text-slate-400 font-mono">
                    {(file.size / 1024).toFixed(1)} KB
                  </div>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFile(null); }}
                    disabled={submitting}
                    className="text-[11px] text-slate-400 hover:text-red-400 transition-colors disabled:opacity-30"
                  >
                    다른 파일 선택
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 text-slate-400 py-2">
                <Upload size={24} className="text-slate-500" />
                <div className="text-xs font-bold text-center">
                  파일을 여기로 끌어다 놓거나 클릭해서 선택
                </div>
                <div className="text-[10px] text-slate-500">
                  jpg / png / webp · 최대 10MB
                </div>
              </div>
            )}
          </div>

          {error && (
            <div className="p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-[11px] text-red-400">
              ⚠ {error}
            </div>
          )}
        </div>

        {/* 버튼 */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 bg-white/5 border-t border-border">
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="px-4 py-1.5 text-xs font-bold text-slate-300 hover:bg-white/5 border border-border rounded-lg transition-colors disabled:opacity-30"
          >
            취소
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!file || submitting}
            className="px-4 py-1.5 text-xs font-bold text-white bg-primary hover:bg-primary/80 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            {submitting ? '교체 중...' : '교체'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
