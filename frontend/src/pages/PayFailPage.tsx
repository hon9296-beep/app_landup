import { useSearchParams, useNavigate } from 'react-router-dom';
import { XCircle } from 'lucide-react';

export default function PayFailPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const code = params.get('code') ?? '';
  const message = params.get('message') ?? '결제에 실패했습니다';

  return (
    <main className="flex-1 flex flex-col items-center justify-center px-6 py-8">
      <XCircle size={64} className="text-red-400 mb-4" />
      <h2 className="text-xl font-bold text-text-main mb-2">결제 실패</h2>
      <p className="text-sm text-text-muted mb-1">{message}</p>
      {code && <p className="text-xs text-text-muted mb-8">오류 코드: {code}</p>}
      <div className="flex gap-3 mt-6">
        <button
          onClick={() => navigate('/pay')}
          className="py-2.5 px-6 rounded-xl bg-primary text-white text-sm font-bold hover:bg-primary/90 transition-colors">
          다시 시도
        </button>
        <button
          onClick={() => navigate('/')}
          className="py-2.5 px-6 rounded-xl border border-border text-text-muted text-sm hover:bg-white/5 transition-colors">
          홈으로
        </button>
      </div>
    </main>
  );
}
