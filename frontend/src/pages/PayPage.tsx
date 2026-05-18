import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Sparkles, ChevronDown, ChevronUp, Zap } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { getCurrentSubscription, type Payment } from '../lib/paymentApi';

interface Plan {
  key: 'basic' | 'premium' | 'max';
  name: string;
  price: string;
  amount: number;
  features: string[];
  highlight?: boolean;
}

const PLANS: Plan[] = [
  {
    key: 'basic',
    name: 'Basic',
    price: '₩0 / 월',
    amount: 0,
    features: ['월 1개 프로젝트', 'AI 공간분석 기반 자동 배치', '단일 세션 (동시 작업 1개)', 'GLB 파일 다운로드'],
  },
  {
    key: 'premium',
    name: 'Premium',
    price: '₩29,000 / 월',
    amount: 29000,
    features: ['월 3개 프로젝트', 'AI 공간분석 기반 자동 배치', 'LLM 기반 재배치 최적화', '월 10회 AI 재배치', '멀티 세션 (동시 작업 3개)', 'GLB 파일 다운로드', '크레딧 구매로 즉시 한도 확장 가능'],
    highlight: true,
  },
  {
    key: 'max',
    name: 'Max',
    price: '₩99,000 / 월',
    amount: 99000,
    features: ['월 10개 프로젝트', 'AI 공간분석 기반 자동 배치', 'LLM 기반 재배치 최적화', '월 30회 AI 재배치', '멀티 세션 (동시 작업 10개)', 'GLB 파일 다운로드', '크레딧 구매로 즉시 한도 확장 가능'],
  },
];

const TOSS_CLIENT_KEY = import.meta.env.VITE_TOSS_CLIENT_KEY ?? '';

export default function PayPage() {
  const navigate = useNavigate();
  const { currentUser, authLoading } = useAuth();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [currentSub, setCurrentSub] = useState<Payment | null>(null);
  const [subLoading, setSubLoading] = useState(true);
  const [upgradeConfirm, setUpgradeConfirm] = useState<Plan | null>(null);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [showLoginModal, setShowLoginModal] = useState(false);

  const FAQS = [
    {
      q: '구독료는 언제 결제되나요?',
      a: '구독 시작일 기준으로 매월 동일한 날짜에 자동 결제됩니다. 예를 들어 4월 15일에 구독했다면 매월 15일에 결제됩니다.',
    },
    {
      q: '구독 취소하면 어떻게 되나요?',
      a: '취소 후에도 남은 구독 기간 동안은 현재 플랜의 모든 혜택이 그대로 유지됩니다. 다음 결제일이 되면 자동으로 Basic 플랜으로 전환됩니다.',
    },
    {
      q: '크레딧이란 무엇인가요?',
      a: '유료 플랜(Premium/Max) 전용 추가 사용권으로, 월 한도를 모두 소진한 후에도 서비스를 계속 이용할 수 있도록 해주는 충전식 포인트입니다.\n프로젝트 추가 생성 1개 = 3크레딧\nAI 재배치 추가 1회 = 1크레딧',
    },
    {
      q: '크레딧은 만료기간이 있나요?',
      a: '크레딧은 별도의 만료 기간 없이 계정 잔액에 누적됩니다. 구독 취소 또는 플랜 변경과 관계없이 보유한 크레딧은 그대로 유지됩니다. 단, 회원 탈퇴 시 잔여 크레딧은 즉시 소멸됩니다.',
    },
    {
      q: '업그레이드하면 기존 프로젝트는 유지되나요?',
      a: '네, 모두 그대로 유지됩니다. 업그레이드 즉시 새 플랜의 한도가 적용되며, 구독 기간과 결제일은 업그레이드일 기준으로 새롭게 시작됩니다.',
    },
    {
      q: 'Basic에서 크레딧 구매가 안 되나요?',
      a: 'Basic 플랜은 크레딧 구매가 불가합니다. 크레딧은 Premium 또는 Max 플랜에서만 구매할 수 있으며, 월 한도 소진 후 추가 사용권으로 활용할 수 있습니다.',
    },
    {
      q: '결제 수단은 무엇을 지원하나요?',
      a: '신용 · 체크카드와 네이버페이, 토스페이 등 간편결제로도 이용하실 수 있습니다.',
    },
    {
      q: '플랜은 언제든지 변경할 수 있나요?',
      a: '언제든지 상위 플랜으로 업그레이드할 수 있습니다. 단, 하위 플랜으로의 다운그레이드는 현재 지원하지 않습니다.',
    },
  ];

  useEffect(() => {
    if (authLoading) return;
    if (!currentUser) { setSubLoading(false); return; }
    setSubLoading(true);
    getCurrentSubscription()
      .then(setCurrentSub)
      .catch(() => {})
      .finally(() => setSubLoading(false));
  }, [authLoading, currentUser]);

  const handlePlanSelect = async (plan: Plan) => {
    if (!currentUser) { toast.error('로그인이 필요합니다'); return; }
    if (plan.amount === 0) { toast.info('해당 플랜은 무료이거나 별도 문의가 필요합니다'); return; }
    setLoading(true);
    try {
      const { loadTossPayments } = await import('@tosspayments/payment-sdk');
      const toss = await loadTossPayments(TOSS_CLIENT_KEY);
      const orderId = `order_${Date.now()}`;
      await toss.requestPayment('카드', {
        amount: plan.amount,
        orderId,
        orderName: `LandUP ${plan.name} 플랜`,
        customerName: currentUser.name,
        successUrl: `${window.location.origin}/pay/success?planName=${plan.name}&price=${encodeURIComponent(plan.price)}&planKey=${plan.key}`,
        failUrl: `${window.location.origin}/pay/fail`,
      });
    } catch (e: any) {
      if (e?.code !== 'USER_CANCEL') toast.error('결제 중 오류가 발생했습니다');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex-1 flex flex-col px-6 py-8">
      <div className="max-w-5xl w-full mx-auto">
        <div className="text-center mb-8">
          <h2 className="text-2xl font-bold text-text-main mb-2">LandUP 멤버십</h2>
          <p className="text-xs text-text-muted">AI가 최적화하는 팝업스토어 공간 설계, 나에게 맞는 플랜을 선택하세요</p>
          {!currentUser && <p className="text-xs text-amber-400 mt-1">로그인 필요</p>}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {PLANS.map(plan => (
            <div key={plan.key} className={`relative bg-black/20 border rounded-2xl p-6 transition-colors flex flex-col ${
              plan.highlight ? 'border-primary/60 shadow-lg shadow-primary/10' : 'border-border hover:border-primary/60'
            }`}>
              {plan.highlight && (
                <div className="absolute -top-2 left-1/2 -translate-x-1/2 bg-primary text-white text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                  <Sparkles size={10} /> 인기
                </div>
              )}
              <h3 className="text-2xl font-bold text-text-main mb-1">{plan.name}</h3>
              <p className="text-base font-bold text-accent mb-4">{plan.price}</p>
              <ul className="space-y-2 mb-6 flex-1">
                {plan.features.map(f => (
                  <li key={f} className="flex items-start gap-2 text-xs text-text-muted">
                    <Check size={12} className="text-accent shrink-0 mt-0.5" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <button
                onClick={() => {
                  if (subLoading) return;
                  if (!currentUser) { setShowLoginModal(true); return; }
                  if (plan.key === 'basic') { navigate('/project'); return; }
                  const isUpgrade = currentSub?.planKey === 'premium' && plan.key === 'max';
                  if (isUpgrade) {
                    setUpgradeConfirm(plan);
                  } else {
                    handlePlanSelect(plan);
                  }
                }}
                disabled={
                  subLoading
                  || loading
                  || (!!currentUser && (
                    currentSub?.planKey === plan.key
                    || (plan.key === 'basic' && ['premium', 'max'].includes(currentSub?.planKey ?? ''))
                    || (plan.key === 'premium' && currentSub?.planKey === 'max')
                  ))
                }
                className={`w-full py-2.5 rounded-xl text-xs font-bold transition-all disabled:cursor-not-allowed ${subLoading ? 'opacity-40' : ''} ${
                  currentUser && currentSub?.planKey === plan.key
                    ? 'bg-primary text-white opacity-80 cursor-not-allowed'
                    : (plan.key === 'premium' && currentSub?.planKey === 'max') || (plan.key === 'basic' && ['premium','max'].includes(currentSub?.planKey ?? ''))
                    ? 'border border-border text-text-muted opacity-40 cursor-not-allowed'
                    : plan.highlight
                    ? 'bg-primary text-white hover:bg-primary/90'
                    : 'border border-border text-text-main hover:bg-primary hover:text-white hover:border-primary'
                }`}>
                {plan.key === 'basic'
                  ? '무료 플랜'
                  : currentUser && currentSub?.planKey === plan.key ? '구독 중'
                  : plan.key === 'premium' && currentSub?.planKey === 'max' ? '이전 플랜'
                  : loading ? '로딩 중...'
                  : '결제하기'}
              </button>
            </div>
          ))}
        </div>

        {/* FAQ */}
        <div className="py-2">
          <div className="flex items-center gap-2 mb-4">
            <h3 className="text-base font-bold text-white">자주 묻는 질문</h3>
            <span className="text-xs font-bold text-slate-400 border border-border px-1.5 py-0.5 rounded">FAQ</span>
          </div>
          <div className="space-y-2">
            {FAQS.map((faq, i) => (
              <div key={i} className="border border-border rounded-xl overflow-hidden">
                <button
                  onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  className="w-full flex items-center justify-between px-4 py-3 text-xs font-bold text-white hover:bg-white/5 transition-colors"
                >
                  <span><span className="text-accent mr-1.5">Q.</span>{faq.q}</span>
                  {openFaq === i ? <ChevronUp size={14} className="text-slate-400 shrink-0" /> : <ChevronDown size={14} className="text-slate-400 shrink-0" />}
                </button>
                {openFaq === i && (
                  <div className="px-4 pb-3 text-xs text-slate-400 leading-relaxed border-t border-border pt-3 whitespace-pre-line">
                    <span className="text-amber-400 font-bold mr-1.5">A.</span>{faq.a}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

      </div>

      {upgradeConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl p-6 space-y-4">
            <h3 className="text-base font-bold text-white">Max 플랜으로 업그레이드</h3>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-white/5 rounded-xl py-3">
                <p className="text-lg font-bold text-accent">10개</p>
                <p className="text-[10px] text-slate-400 mt-0.5">월 프로젝트</p>
              </div>
              <div className="bg-white/5 rounded-xl py-3">
                <p className="text-lg font-bold text-accent">30회</p>
                <p className="text-[10px] text-slate-400 mt-0.5">월 재배치</p>
              </div>
              <div className="bg-white/5 rounded-xl py-3">
                <p className="text-lg font-bold text-accent">10개</p>
                <p className="text-[10px] text-slate-400 mt-0.5">동시 작업</p>
              </div>
            </div>
            <p className="text-xs text-white font-bold">업그레이드 즉시 모든 한도가 적용됩니다.</p>
            <p className="text-[11px] text-slate-400">업그레이드 시 새로운 구독 기간이 시작되며, 이전 구독료는 환불되지 않습니다.</p>
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => { setUpgradeConfirm(null); handlePlanSelect(upgradeConfirm); }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold bg-primary text-white hover:bg-primary/90 transition-colors"
              >
                지금 업그레이드
              </button>
              <button
                onClick={() => setUpgradeConfirm(null)}
                className="flex-1 py-2.5 rounded-xl text-sm text-slate-400 border border-border hover:bg-white/5 transition-colors"
              >
                취소
              </button>
            </div>
          </div>
        </div>
      )}

      {showLoginModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl p-6 space-y-4 text-center">
            <h3 className="text-base font-bold text-white">로그인이 필요한 서비스입니다</h3>
            <p className="text-xs text-slate-400">로그인 후 이용하실 수 있습니다.</p>
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => { setShowLoginModal(false); navigate('/login'); }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold bg-primary text-white hover:bg-primary/90 transition-colors"
              >
                로그인하러 가기
              </button>
              <button
                onClick={() => setShowLoginModal(false)}
                className="flex-1 py-2.5 rounded-xl text-sm text-slate-400 border border-border hover:bg-white/5 transition-colors"
              >
                취소
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
