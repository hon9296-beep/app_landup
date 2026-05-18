/**
 * 썸네일 클릭 시 원본 이미지를 화면 중앙에 띄우는 라이트박스.
 *
 * 기능:
 *   - 마우스 휠: zoom in/out (0.5x ~ 8x)
 *   - 드래그: pan (이동)
 *   - 더블클릭: 1x 리셋
 *   - ESC 키 / 배경 클릭 / X 버튼: 닫기
 *
 * 외부 라이브러리 없음 — React state + CSS transform 만 사용.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface Props {
  src: string;
  alt: string;
  onClose: () => void;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 8;
const SCALE_STEP = 1.15;

export default function RefImageLightbox({ src, alt, onClose }: Props) {
  const [scale, setScale] = useState(1);
  const [tx, setTx] = useState(0);
  const [ty, setTy] = useState(0);
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });

  const overlayRef = useRef<HTMLDivElement | null>(null);

  // ESC 닫기 + body scroll lock (모달 열린 동안 페이지 스크롤 차단)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  // wheel 처리 — Ctrl/Cmd 누른 상태에서만 zoom. 그 외엔 차단(아무 동작 없음).
  // React onWheel 은 passive 라 preventDefault 안 먹힘 → ref + native addEventListener.
  useEffect(() => {
    const el = overlayRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      if (!(e.ctrlKey || e.metaKey)) return; // Ctrl/Cmd 안 누르면 zoom 안 함
      setScale((s) => {
        const next = e.deltaY < 0 ? s * SCALE_STEP : s / SCALE_STEP;
        return Math.max(MIN_SCALE, Math.min(MAX_SCALE, next));
      });
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, []);

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, tx, ty };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging) return;
    setTx(dragStart.current.tx + (e.clientX - dragStart.current.x));
    setTy(dragStart.current.ty + (e.clientY - dragStart.current.y));
  };
  const stopDrag = () => setDragging(false);

  const onDoubleClick = () => {
    setScale(1);
    setTx(0);
    setTy(0);
  };

  const onBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  };

  return createPortal(
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 bg-black/85 select-none"
      onClick={onBackdropClick}
      onMouseMove={onMouseMove}
      onMouseUp={stopDrag}
      onMouseLeave={stopDrag}
    >
      {/* 닫기 버튼 — 우상단 */}
      <button
        type="button"
        onClick={onClose}
        className="absolute top-4 right-4 text-white/70 hover:text-white transition-colors p-2 bg-black/40 rounded-full"
        aria-label="닫기"
      >
        <X size={20} />
      </button>

      {/* 안내 텍스트 — 좌하단 */}
      <div className="absolute bottom-4 left-4 text-[11px] text-white/60 font-bold space-x-3">
        <span>Ctrl + 휠: 확대/축소</span>
        <span>드래그: 이동</span>
        <span>더블클릭: 리셋</span>
        <span>ESC: 닫기</span>
        <span className="text-white/80">{(scale * 100).toFixed(0)}%</span>
      </div>

      {/* 이미지 — absolute + translate(-50%) 로 viewport 정중앙. 부모 transform 영향 없음 */}
      <img
        src={src}
        alt={alt}
        draggable={false}
        onMouseDown={onMouseDown}
        onDoubleClick={onDoubleClick}
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: `translate(-50%, -50%) translate(${tx}px, ${ty}px) scale(${scale})`,
          transformOrigin: 'center center',
          cursor: dragging ? 'grabbing' : 'grab',
          maxWidth: '90vw',
          maxHeight: '90vh',
          transition: dragging ? 'none' : 'transform 0.05s linear',
        }}
      />
    </div>,
    document.body,
  );
}
