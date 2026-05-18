/**
 * ToastContext — 전역 토스트 알림 시스템
 *
 * B-7 비동기 작업 완료·실패 알림용.
 *
 * 사용:
 *   const { toast } = useToast();
 *   toast.success('분석 완료');
 *   toast.error('실패: 네트워크 오류');
 */
import {
  createContext, useCallback, useContext, useRef, useState,
  type ReactNode,
} from 'react';
import { CheckCircle2, XCircle, Info } from 'lucide-react';

type ToastType = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  persistent?: boolean;
}

interface ToastAPI {
  success: (message: string, opts?: { actionLabel?: string; onAction?: () => void }) => void;
  error: (message: string, opts?: { persistent?: boolean }) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<{ toast: ToastAPI } | null>(null);

const DURATION_MS = 5000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((type: ToastType, message: string, opts?: { actionLabel?: string; onAction?: () => void; persistent?: boolean }) => {
    const id = nextId.current++;
    setItems(prev => [...prev, { id, type, message, actionLabel: opts?.actionLabel, onAction: opts?.onAction, persistent: opts?.persistent }]);
    if (!opts?.persistent) {
      setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), DURATION_MS);
    }
  }, []);

  const toast: ToastAPI = {
    success: (m, opts) => push('success', m, opts),
    error: (m, opts) => push('error', m, opts),
    info: (m) => push('info', m),
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {/* 우하단 고정 — 드롭다운(우상단) 가리지 않음. 최신 토스트가 맨 아래, 위로 쌓임 */}
      <div className="fixed bottom-4 right-4 z-[1000] flex flex-col-reverse gap-2 pointer-events-none">
        {items.map(t => (
          <div
            key={t.id}
            className={`pointer-events-auto min-w-[260px] max-w-[400px] px-4 py-3 rounded-xl border shadow-lg flex items-start gap-2.5 backdrop-blur-sm animate-in slide-in-from-bottom-2
              ${t.type === 'success' ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300' : ''}
              ${t.type === 'error' ? 'bg-red-500/10 border-red-500/40 text-red-300' : ''}
              ${t.type === 'info' ? 'bg-sky-500/10 border-sky-500/40 text-sky-300' : ''}
            `}
          >
            {t.type === 'success' && <CheckCircle2 size={16} className="shrink-0 mt-0.5" />}
            {t.type === 'error' && <XCircle size={16} className="shrink-0 mt-0.5" />}
            {t.type === 'info' && <Info size={16} className="shrink-0 mt-0.5" />}
            <div className="flex-1 text-xs leading-relaxed">
              <p>{t.message}</p>
              {t.actionLabel && t.onAction && (
                <button
                  onClick={() => { t.onAction!(); setItems(prev => prev.filter(x => x.id !== t.id)); }}
                  className="mt-1 text-[11px] font-semibold underline hover:no-underline"
                >
                  {t.actionLabel}
                </button>
              )}
              {t.persistent && (
                <button
                  onClick={() => setItems(prev => prev.filter(x => x.id !== t.id))}
                  className="mt-2 block px-3 py-1 rounded-lg bg-red-500/20 hover:bg-red-500/30 text-[11px] font-semibold transition-colors"
                >
                  확인
                </button>
              )}
            </div>
            {!t.persistent && (
              <button
                onClick={() => setItems(prev => prev.filter(x => x.id !== t.id))}
                className="text-current opacity-50 hover:opacity-100 text-xs"
              >✕</button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
