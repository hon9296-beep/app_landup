/**
 * GlbExportButton — `.glb` 버튼 + 팝오버 (파일명 입력 + zone 포함/제외 체크박스).
 *
 * 2군데에서 재사용:
 *   - ViewerActionButtons (3D 뷰 우측 인라인 툴바)
 *   - ResultPage 상단 서브툴바 (좌측 저장하기 옆)
 *
 * 팝오버:
 *   [파일명 input]
 *   → 미리보기 텍스트 (선택 상태에 맞춰 실제 다운로드 파일명 표시)
 *   [☐ zone 포함]
 *   [☑ zone 제외]
 *   [다운로드]
 *
 * 체크 2개 모두 선택 시 2개 파일 순차 다운로드. 모두 미선택 시 버튼 disabled.
 */
import { useEffect, useRef, useState } from 'react';

interface Props {
  /** 다운로드 트리거 — includeZones, 파일명(확장자 제외), includeFloorTexture 전달 */
  onExport: (includeZones: boolean, filename: string, includeFloorTexture: boolean) => void;
  /** 팝오버 파일명 input 기본값 (보통 프로젝트 이름). async 도착 허용 — 사용자가 직접 수정 전이면 sync */
  defaultFilename?: string | null;
  /** 버튼 자체 스타일 override. 기본은 dark pill. 팔레트/뷰어 맞춤 */
  buttonClassName?: string;
  /** 버튼 내부 내용 (아이콘 + 텍스트 등). 기본은 '.glb' 텍스트만 */
  buttonContent?: React.ReactNode;
  /** 버튼 title (hover tooltip) */
  buttonTitle?: string;
}

export default function GlbExportButton({
  onExport,
  defaultFilename,
  buttonClassName,
  buttonContent,
  buttonTitle,
}: Props) {
  const [open, setOpen] = useState(false);
  const [optInclude, setOptInclude] = useState(false);
  const [optExclude, setOptExclude] = useState(true);
  const [optFloorTexture, setOptFloorTexture] = useState(true);
  const [filename, setFilename] = useState(defaultFilename?.trim() || 'popup_layout');
  const userEditedRef = useRef(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // defaultFilename 이 async 로 늦게 도착해도 사용자가 수정 전이면 sync
  useEffect(() => {
    if (userEditedRef.current) return;
    if (defaultFilename && defaultFilename.trim()) {
      setFilename(defaultFilename.trim());
    }
  }, [defaultFilename]);

  // 바깥 클릭 시 팝오버 닫기
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!popoverRef.current) return;
      if (!popoverRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const handleDownload = () => {
    // OS 파일명 금지 문자 (/ \ : * ? " < > |) → _ 로 치환. 공백 trim. 빈 값 fallback.
    const cleaned = filename.trim().replace(/[\/\\:*?"<>|]/g, '_') || 'popup_layout';
    if (optInclude) onExport(true, cleaned, optFloorTexture);
    if (optExclude) onExport(false, cleaned, optFloorTexture);
    setOpen(false);
  };

  const defaultBtn =
    'text-xs text-white bg-slate-800 hover:bg-slate-700 border border-slate-700/60 px-3 py-1.5 rounded-lg transition-all font-bold';

  return (
    <div ref={popoverRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className={buttonClassName ?? defaultBtn}
        title={buttonTitle}
      >
        {buttonContent ?? '.glb'}
      </button>
      {open && (
        <div className="absolute left-0 top-full mt-1 w-56 bg-white border border-slate-200 rounded-lg shadow-lg p-2.5 z-50 flex flex-col gap-2">
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-slate-500 font-medium">파일명 (확장자 자동)</label>
            <input
              type="text"
              value={filename}
              onChange={(e) => { userEditedRef.current = true; setFilename(e.target.value); }}
              onKeyDown={(e) => { if (e.key === 'Enter' && (optInclude || optExclude)) handleDownload(); }}
              placeholder="popup_layout"
              className="w-full text-[11px] px-2 py-1 border border-slate-200 rounded focus:outline-none focus:border-slate-400 text-slate-700"
            />
            <span className="text-[10px] text-slate-400">
              → {filename.trim() || 'popup_layout'}{optExclude ? '.glb' : ''}{optInclude && optExclude ? ' + ' : ''}{optInclude ? (filename.trim() || 'popup_layout') + '_zone.glb' : ''}
            </span>
          </div>
          <div className="flex flex-col gap-1 border-t border-slate-100 pt-2">
            <label className="flex items-center gap-2 text-[11px] text-slate-700 cursor-pointer select-none px-1.5 py-1 rounded hover:bg-slate-50">
              <input
                type="checkbox"
                checked={optInclude}
                onChange={(e) => setOptInclude(e.target.checked)}
                className="accent-slate-700 cursor-pointer"
              />
              zone 포함
            </label>
            <label className="flex items-center gap-2 text-[11px] text-slate-700 cursor-pointer select-none px-1.5 py-1 rounded hover:bg-slate-50">
              <input
                type="checkbox"
                checked={optExclude}
                onChange={(e) => setOptExclude(e.target.checked)}
                className="accent-slate-700 cursor-pointer"
              />
              zone 제외
            </label>
          </div>
          <div className="flex flex-col gap-1 border-t border-slate-100 pt-2">
            <label className="flex items-center gap-2 text-[11px] text-slate-700 cursor-pointer select-none px-1.5 py-1 rounded hover:bg-slate-50">
              <input
                type="checkbox"
                checked={optFloorTexture}
                onChange={(e) => setOptFloorTexture(e.target.checked)}
                className="accent-slate-700 cursor-pointer"
              />
              바닥 패턴 포함
            </label>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            disabled={!optInclude && !optExclude}
            className="px-2 py-1.5 text-[11px] bg-slate-800 hover:bg-slate-700 text-white rounded-md transition-colors border border-slate-700/60 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            다운로드
          </button>
        </div>
      )}
    </div>
  );
}
