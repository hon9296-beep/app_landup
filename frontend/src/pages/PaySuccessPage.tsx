/**
 * PaySuccessPage — 일반결제 완료 후 토스 리다이렉트 처리
 * 토스가 successUrl로 리다이렉트할 때 ?paymentKey=&orderId=&amount= 쿼리 파라미터 전달
 */
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle, XCircle } from 'lucide-react';
import { confirmPayment, purchaseCredits, type Payment } from '../lib/paymentApi';
import { useAuth } from '../context/AuthContext';

export default function PaySuccessPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { authLoading, updateUser } = useAuth();
  const [payment, setPayment] = useState<Payment | null>(null);
  const [error, setError] = useState('');

  const type = params.get('type') ?? '';          // 'credit' or ''
  const planName = params.get('planName') ?? '';
  const price = params.get('price') ?? '';
  const planKey = params.get('planKey') ?? '';
  const creditAmount = Number(params.get('creditAmount') ?? '0');

  useEffect(() => {
    if (authLoading) return; // 토큰 복원 완료 후 호출

    const paymentKey = params.get('paymentKey');
    const orderId = params.get('orderId');
    const amount = params.get('amount');

    if (!paymentKey || !orderId || !amount) {
      setError('결제 정보가 올바르지 않습니다');
      return;
    }

    if (type === 'credit') {
      purchaseCredits({ paymentKey, orderId, amount: Number(amount), creditAmount })
        .then(p => setPayment(p))
        .catch(() => setError('크레딧 충전 승인에 실패했습니다'));
    } else {
      confirmPayment({
        paymentKey,
        orderId,
        amount: Number(amount),
        description: planName ? `LandUP ${planName} 플랜` : 'LandUP 플랜',
        planKey,
      })
        .then(p => { setPayment(p); if (planKey) updateUser({ membership: planKey }); })
        .catch(() => setError('결제 승인에 실패했습니다'));
    }
  }, [authLoading]);

  if (error) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-8">
        <XCircle size={64} className="text-red-400 mb-4" />
        <h2 className="text-xl font-bold text-text-main mb-2">결제 실패</h2>
        <p className="text-xs text-text-muted mb-8">{error}</p>
        <button onClick={() => navigate('/pay')}
          className="py-3 px-6 rounded-xl bg-primary text-white text-sm font-bold hover:bg-primary/90 transition-colors">
          다시 시도
        </button>
      </main>
    );
  }

  if (!payment) {
    return (
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-8">
        <p className="text-xs text-text-muted">결제 확인 중...</p>
      </main>
    );
  }

  return (
    <main className="flex-1 flex flex-col px-6 py-8">
      <div className="max-w-sm mx-auto text-center">
        <div className="flex justify-center mb-6">
          <CheckCircle size={64} className="text-green-400" />
        </div>
        <h2 className="text-2xl font-bold text-text-main mb-2">
          {type === 'credit' ? '크레딧 충전 완료' : '결제 완료'}
        </h2>
        <p className="text-xs text-text-muted mb-8">
          {type === 'credit'
            ? `${creditAmount} 크레딧이 잔액에 추가되었습니다`
            : '결제가 성공적으로 완료되었습니다'}
        </p>

        <div className="bg-black/20 border border-border rounded-2xl p-6 text-left space-y-3 mb-8">
          {type === 'credit' ? (
            <div className="flex justify-between items-center">
              <span className="text-xs text-text-muted">충전 크레딧</span>
              <span className="text-sm font-bold text-amber-400">{creditAmount} cr</span>
            </div>
          ) : planName && (
            <div className="flex justify-between items-center">
              <span className="text-xs text-text-muted">플랜</span>
              <span className="text-sm font-bold text-text-main">{planName}</span>
            </div>
          )}
          {price && (
            <div className="flex justify-between items-center">
              <span className="text-xs text-text-muted">결제 금액</span>
              <span className="text-sm font-bold text-accent">{price}</span>
            </div>
          )}
          <div className="flex justify-between items-center">
            <span className="text-xs text-text-muted">주문번호</span>
            <span className="text-xs text-text-muted font-mono">{payment.orderId}</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-text-muted">결제일시</span>
            <span className="text-xs text-text-muted">
              {new Date(payment.createdAt + 'Z').toLocaleString('ko-KR')}
            </span>
          </div>
          {payment.nextBillingDate && (
            <div className="flex justify-between items-center">
              <span className="text-xs text-text-muted">다음 결제일</span>
              <span className="text-xs text-text-muted">
                {new Date(payment.nextBillingDate + 'Z').toLocaleDateString('ko-KR')}
              </span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <button onClick={() => navigate('/mypage')}
            className="w-full py-3 rounded-xl bg-primary text-white text-sm font-bold hover:bg-primary/90 transition-colors">
            결제내역 보기
          </button>
          <button onClick={() => navigate('/')}
            className="w-full py-3 rounded-xl border border-border text-text-muted text-sm hover:bg-white/5 transition-colors">
            홈으로
          </button>
        </div>
      </div>
    </main>
  );
}
