import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Pencil, Check, X, CreditCard, Zap, Coins, ChevronRight, ChevronLeft, ArrowUpCircle } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import axiosClient from '../lib/axiosClient'
import {
  getPaymentHistory, getPlanLimits, getCreditHistory, cancelSubscription,
  type Payment, type PlanLimitStatus, type CreditTransaction,
} from '../lib/paymentApi'
import { USE_DIRECT } from '../lib/api'

function fmtDate(dt: string | null | undefined): string {
  if (!dt) return '-'
  const d = new Date(dt)
  if (isNaN(d.getTime())) return '-'
  const yy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${yy}.${mm}.${dd} ${hh}:${min}`
}

function fmtDateOnly(dt: string | null | undefined): string {
  if (!dt) return '-'
  const d = new Date(dt)
  if (isNaN(d.getTime())) return '-'
  const yy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yy}.${mm}.${dd}`
}

// ── 내정보수정 ─────────────────────────────────────────────
function UserInfoSection() {
  const { currentUser, updateUser } = useAuth()
  const [phone, setPhone] = useState('')
  const [phoneLoaded, setPhoneLoaded] = useState(false)
  const [isVerified, setIsVerified] = useState<boolean | null>(null)
  const [authMethod, setAuthMethod] = useState<string>('')
  const [joinedAt, setJoinedAt] = useState<string>('')
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editPhone, setEditPhone] = useState('')
  const [saving, setSaving] = useState(false)
  const [profileError, setProfileError] = useState('')
  // 백엔드 검증 실패 시 필드별 메시지 (errors 객체 응답) — input 아래 인라인 노출
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; phone?: string }>({})

  useEffect(() => {
    if (!currentUser) return
    // [LOCAL_TEST_USE_DIRECT] Java/DB 미경유 — /me fetch skip, dummy 빈 전화번호
    if (USE_DIRECT) { setPhoneLoaded(true); return }
    axiosClient.get('/me')
      .then(res => {
        setPhone(res.data.phone ?? '')
        setIsVerified(res.data.isVerified ?? false)
        setAuthMethod(res.data.authMethod ?? '')
        setJoinedAt(res.data.created_at ?? '')
        setPhoneLoaded(true)
      })
      .catch(() => setPhoneLoaded(true))
  }, [currentUser?.id])

  const startEdit = () => {
    setEditName(currentUser?.name ?? '')
    setEditPhone(phone)
    setEditing(true)
    setProfileError('')
    setFieldErrors({})
  }

  const cancel = () => { setEditing(false); setProfileError(''); setFieldErrors({}) }

  const save = async () => {
    if (!currentUser) return

    if (USE_DIRECT) { setProfileError('직통 모드는 DB 미경유 — 저장 불가'); return }
    setSaving(true); setProfileError(''); setFieldErrors({})

    try {
      const res = await axiosClient.patch('/me', {
        name: editName || null,
        phone: editPhone || null,
      })
      updateUser({ name: res.data.name })
      setPhone(res.data.phone ?? '')
      setEditing(false)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string; errors?: Record<string, string> } } }
      const data = err.response?.data
      if (data?.errors && Object.keys(data.errors).length > 0) {
        setFieldErrors({ name: data.errors.name, phone: data.errors.phone })
        // 필드별 인라인 메시지가 충분 — 상단 일반 에러는 비움
      } else {
        setProfileError(data?.detail || '저장에 실패했습니다.')
      }
    }
    finally { setSaving(false) }
  }

  return (
    <div className="bg-slate-800 border border-border rounded-xl shadow-sm">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <span className="text-sm font-bold text-white">내정보수정</span>
        <div className="flex items-center gap-1">
          {editing ? (
            <>
              <button onClick={save} disabled={saving}
                className="p-1.5 rounded-lg text-accent hover:bg-accent/20 transition-colors disabled:opacity-50">
                <Check size={15} />
              </button>
              <button onClick={cancel}
                className="px-3 py-1.5 text-sm text-slate-300 border-b border-border bg-white/5 hover:bg-white/10 border border-border rounded-lg transition-colors">
                <X size={15} />
              </button>
            </>
          ) : (
            <button onClick={startEdit}
              className="p-1.5 rounded-lg text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors"
              title="이름·전화번호 편집">
              <Pencil size={15} />
            </button>
          )}
        </div>
      </div>

      <div className="px-5 py-4 space-y-3">
        <div className="flex items-start gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0 mt-2">이름</span>
          {editing
            ? <div className="flex-1 max-w-xs">
                <input value={editName} onChange={e => { setEditName(e.target.value); setFieldErrors(p => ({ ...p, name: undefined })) }}
                  className={`w-full bg-slate-900 border rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none transition-colors ${
                    fieldErrors.name ? 'border-red-500/60 focus:border-red-500' : 'border-border focus:border-primary'
                  }`} />
                {fieldErrors.name && (
                  <p className="mt-1 text-[11px] text-red-400">{fieldErrors.name}</p>
                )}
              </div>
            : <span className="text-sm font-bold text-white">{currentUser?.name ?? '-'}</span>
          }
        </div>
        <div className="flex items-start gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0 mt-2">전화번호</span>
          {editing
            ? <div className="flex-1 max-w-xs">
                <input value={editPhone} onChange={e => { setEditPhone(e.target.value.replace(/\D/g, '')); setFieldErrors(p => ({ ...p, phone: undefined })) }}
                  placeholder="01000000000"
                  inputMode="numeric"
                  maxLength={11}
                  className={`w-full bg-slate-900 border rounded-lg px-3 py-1.5 text-white text-sm focus:outline-none transition-colors ${
                    fieldErrors.phone ? 'border-red-500/60 focus:border-red-500' : 'border-border focus:border-primary'
                  }`} />
                {fieldErrors.phone && (
                  <p className="mt-1 text-[11px] text-red-400">{fieldErrors.phone}</p>
                )}
              </div>
            : <span className="text-sm text-slate-400">{phoneLoaded ? (phone || '-') : '...'}</span>
          }
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0">이메일</span>
          <span className="text-sm text-slate-400">{currentUser?.email ?? '-'}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0">멤버십</span>
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-primary capitalize">{currentUser?.membership ?? '-'}</span>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0">이메일 인증</span>
          {isVerified === null
            ? <span className="text-sm text-slate-500">...</span>
            : <span className={`text-sm font-medium ${isVerified ? 'text-accent' : 'text-amber-400'}`}>
                {isVerified ? '이메일인증완료' : '이메일인증미완료'}
              </span>
          }
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0">인증방법</span>
          <span className="text-sm text-slate-400">{phoneLoaded ? (authMethod || '-') : '...'}</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500 w-20 shrink-0">가입일</span>
          <span className="text-sm text-slate-400">{phoneLoaded ? (fmtDateOnly(joinedAt) || '-') : '...'}</span>
        </div>
      </div>

      {profileError && (
        <div className="mx-5 mb-4 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          {profileError}
        </div>
      )}
    </div>
  )
}

// ── 크레딧 구매 팩 정의 ──────────────────────────────────
const CREDIT_PACKS = [
  { credit: 10,  amount: 5000 },
  { credit: 30,  amount: 12000 },
  { credit: 90,  amount: 36000 },
]

const TOSS_CLIENT_KEY = import.meta.env.VITE_TOSS_CLIENT_KEY ?? ''

// ── 플랜 한도 현황 ─────────────────────────────────────
function PlanLimitSection() {
  const { authLoading, currentUser } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState<PlanLimitStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [showCreditModal, setShowCreditModal] = useState(false)
  const [creditError, setCreditError] = useState('')

  const isBasic = status && status.membership.toLowerCase() === 'basic'
  const canBuyCredits = status && status.membership.toLowerCase() !== 'basic'

  useEffect(() => {
    if (authLoading || USE_DIRECT) { setLoading(false); return }
    getPlanLimits()
      .then(setStatus)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [authLoading])

  const handleCreditPurchase = async (pack: typeof CREDIT_PACKS[0]) => {
    setCreditError('')
    try {
      const { loadTossPayments } = await import('@tosspayments/payment-sdk')
      const toss = await loadTossPayments(TOSS_CLIENT_KEY)
      await toss.requestPayment('카드', {
        amount: pack.amount,
        orderId: `credit_${Date.now()}`,
        orderName: `LandUP ${pack.credit} 크레딧`,
        customerName: currentUser?.name ?? '',
        successUrl: `${window.location.origin}/pay/success?type=credit&creditAmount=${pack.credit}&price=${encodeURIComponent(`${pack.amount.toLocaleString()}원`)}`,
        failUrl: `${window.location.origin}/pay/fail`,
      })
    } catch (e: unknown) {
      if ((e as { code?: string }).code !== 'USER_CANCEL') setCreditError('결제 중 오류가 발생했습니다.')
    }
  }

  function LimitBar({ used, max, label }: { used: number; max: number; label: string }) {
    const pct = max === 0 ? 100 : Math.min((used / max) * 100, 100)
    const isOver = used >= max
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-xs">
          <span className="text-slate-400">{label}</span>
          <span className={isOver ? 'text-red-400 font-bold' : 'text-slate-300'}>
            {max >= 2147483647 ? '무제한' : `${used} / ${max}`}
          </span>
        </div>
        {max < 2147483647 && (
          <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${isOver ? 'bg-red-400' : 'bg-primary'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        )}
      </div>
    )
  }

  if (loading) return null

  return (
    <div className="bg-slate-800 border border-border rounded-xl shadow-sm">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <span className="text-sm font-bold text-white">이달의 사용 현황</span>
      </div>

      {status && (
        <div className="px-5 py-4 space-y-4">
          <LimitBar used={status.usedProjects}   max={status.maxProjects}   label="프로젝트 생성" />
          <LimitBar used={status.usedRedeploys}  max={status.maxRedeploys}  label="재배치 횟수" />
          <LimitBar used={status.usedConcurrent} max={status.maxConcurrent} label="동시 작업" />

          <div className="flex items-center justify-between pt-1 border-t border-border">
            <div className="flex items-center gap-2">
              <span className="text-xs text-amber-400">크레딧 잔액</span>
              <span className="text-xs font-bold text-amber-400">{status.creditBalance} 크레딧</span>
            </div>
            {canBuyCredits && (
              <button
                onClick={() => { setShowCreditModal(true); setCreditError('') }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg bg-amber-400/10 text-amber-400 border border-amber-400/30 hover:bg-amber-400/20 transition-colors"
              >
                <CreditCard size={12} />
                크레딧 구매
              </button>
            )}
          </div>

          {isBasic && (
            <div className="space-y-2">
              <p className="text-[11px] text-slate-500 text-center">
                크레딧 구매는 Premium / Max 플랜에서만 가능합니다.
              </p>
              <div className="flex items-center justify-between pt-1 border-t border-border">
                <p className="text-[11px] text-slate-500">더 많은 기능이 필요하신가요?</p>
                <button
                  onClick={() => navigate('/pay')}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
                >
                  <ArrowUpCircle size={12} />
                  플랜 업그레이드
                </button>
              </div>
            </div>
          )}
</div>
      )}

      {/* 크레딧 구매 모달 */}
      {showCreditModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <span className="text-sm font-bold text-white">크레딧 구매</span>
              <button onClick={() => setShowCreditModal(false)} className="text-slate-400 hover:text-white transition-colors">
                <X size={16} />
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500 bg-white/5 rounded-xl px-3 py-2">
                <span className="whitespace-nowrap">재배치 1회 = 1 크레딧</span>
                <span className="text-slate-600">·</span>
                <span className="whitespace-nowrap">프로젝트 추가 = 3 크레딧</span>
                <span className="text-slate-600">·</span>
                <span className="whitespace-nowrap">즉시 충전 · 만료 없음</span>
              </div>
              {CREDIT_PACKS.map(pack => (
                <button
                  key={pack.credit}
                  onClick={() => handleCreditPurchase(pack)}
                  className="w-full flex items-center justify-between px-4 py-3.5 rounded-xl border-b border-border bg-white/5 hover:bg-amber-400/10 border border-border hover:border-amber-400/40 transition-all group"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-amber-400/10 flex items-center justify-center group-hover:bg-amber-400/20 transition-colors">
                      <Zap size={14} className="text-amber-400" fill="currentColor" />
                    </div>
                    <p className="text-sm font-bold text-white">{pack.credit} 크레딧</p>
                  </div>
                  <span className="text-sm font-bold text-amber-400">₩{pack.amount.toLocaleString()}</span>
                </button>
              ))}
              {creditError && (
                <p className="text-xs text-red-400 flex items-center gap-1">
                  <AlertCircle size={11} /> {creditError}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── 공통 페이지네이션 ──────────────────────────────────────
function Pagination({ page, totalPages, onChange }: {
  page: number; totalPages: number; onChange: (p: number) => void
}) {
  if (totalPages <= 1) return null
  const delta = 2
  const left = Math.max(0, page - delta)
  const right = Math.min(totalPages - 1, page + delta)
  const range: number[] = []
  for (let i = left; i <= right; i++) range.push(i)

  return (
    <div className="flex items-center justify-center gap-1.5 py-3">
      <button onClick={() => onChange(page - 1)} disabled={page === 0}
        className="p-1.5 rounded-lg border-b border-border bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
        <ChevronLeft size={13} />
      </button>
      {left > 0 && (
        <>
          <button onClick={() => onChange(0)}
            className="w-7 h-7 rounded-lg text-xs border-b border-border bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors">1</button>
          {left > 1 && <span className="text-slate-600 text-xs px-1">…</span>}
        </>
      )}
      {range.map(i => (
        <button key={i} onClick={() => onChange(i)}
          className={`w-7 h-7 rounded-lg text-xs font-bold transition-colors ${i === page ? 'bg-primary text-white' : 'border-b border-border bg-white/5 hover:bg-white/10 border border-border text-slate-300'}`}>
          {i + 1}
        </button>
      ))}
      {right < totalPages - 1 && (
        <>
          {right < totalPages - 2 && <span className="text-slate-600 text-xs px-1">…</span>}
          <button onClick={() => onChange(totalPages - 1)}
            className="w-7 h-7 rounded-lg text-xs border-b border-border bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors">{totalPages}</button>
        </>
      )}
      <button onClick={() => onChange(page + 1)} disabled={page >= totalPages - 1}
        className="p-1.5 rounded-lg border-b border-border bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors disabled:opacity-30 disabled:cursor-not-allowed">
        <ChevronRight size={13} />
      </button>
    </div>
  )
}

// ── 결제이력 ───────────────────────────────────────────────
const STATUS_LABEL: Record<string, string> = {
  pending: '대기', success: '성공', failed: '실패', cancelled: '취소',
}
const STATUS_COLOR: Record<string, string> = {
  pending:   'text-amber-400 bg-amber-400/10 border-amber-400/20',
  success:   'text-accent bg-accent/20 border-accent/30',
  failed:    'text-red-400 bg-red-500/10 border-red-500/30',
  cancelled: 'text-slate-400 border-b border-border bg-white/5 border-border',
}

const PAGE_SIZE = 10

function PaymentsSection() {
  const { authLoading } = useAuth()
  const [payments, setPayments] = useState<Payment[]>([])
  const [loading, setLoading] = useState(true)
  const [paymentError, setPaymentError] = useState('')
  const [selected, setSelected] = useState<Payment | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState('')
  const [showConfirm, setShowConfirm] = useState(false)
  const [cancelDone, setCancelDone] = useState(false)
  const [payPage, setPayPage] = useState(0)

  useEffect(() => {
    if (authLoading) return
    if (USE_DIRECT) { setPayments([]); setLoading(false); return }
    getPaymentHistory()
      .then(data => setPayments(data.filter(p => p.type === 'SUBSCRIPTION')))
      .catch(() => setPaymentError('결제 내역을 불러오는데 실패했습니다.'))
      .finally(() => setLoading(false))
  }, [authLoading])

  const handleCancel = async () => {
    if (!selected) return
    setCancelling(true)
    setCancelError('')
    try {
      const updated = await cancelSubscription()
      setPayments(prev => prev.map(p => p.id === updated.id ? updated : p))
      setSelected(updated)
      setCancelDone(true)
    } catch {
      setCancelError('구독 취소에 실패했습니다. 다시 시도해주세요.')
    } finally {
      setCancelling(false)
    }
  }

  return (
    <div className="bg-slate-800 border border-border rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3 border-b border-border">
        <span className="text-sm font-bold text-white">구독 결제이력</span>
      </div>

      {paymentError && (
        <div className="mx-5 my-4 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          {paymentError}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-10">
          <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!loading && !paymentError && payments.length === 0 && (
        <p className="text-slate-500 text-xs text-center py-10">결제 내역이 없습니다.</p>
      )}

      {!loading && !paymentError && payments.length > 0 && (() => {
        const activeId = (payments[0]?.status === 'success' && !payments[0]?.cancelledAt) ? payments[0].id : undefined

        const getSubStatus = (p: Payment) => {
          if (p.status === 'cancelled') return { label: '결제 취소', cls: 'text-red-400 bg-red-500/10 border-red-500/30' }
          if (p.status !== 'success') return null
          if (p.cancelledAt) return { label: '구독 취소', cls: 'text-slate-400 bg-white/5 border-border' }
          if (p.id === activeId) return { label: '구독 중', cls: 'text-accent bg-accent/20 border-accent/30' }
          return { label: '이전 플랜', cls: 'text-slate-400 bg-white/5 border-border' }
        }

        const getNextBillingDisplay = (p: Payment) => {
          if (p.status === 'cancelled') return '-'
          if (p.status === 'success' && !p.cancelledAt && p.id !== activeId) return '-'
          return fmtDateOnly(p.nextBillingDate)
        }

        const totalPages = Math.ceil(payments.length / PAGE_SIZE)
        const firstPageSize = payments.length % PAGE_SIZE || PAGE_SIZE
        const startIdx = payPage === 0 ? 0 : firstPageSize + (payPage - 1) * PAGE_SIZE
        const paged = payments.slice(startIdx, startIdx + (payPage === 0 ? firstPageSize : PAGE_SIZE))

        return (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full text-left table-fixed">
                <colgroup>
                  <col className="w-12" />
                  <col className="w-36" />
                  <col className="w-28" />
                  <col className="w-28" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead>
                  <tr className="border-b border-border bg-white/5">
                    {['No.', '플랜', '금액', '결제일', '다음결제일', '상태'].map(h => (
                      <th key={h} className="px-3 py-2 text-xs text-slate-400 font-bold uppercase tracking-wide whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paged.map(p => {
                    const sub = getSubStatus(p)
                    return (
                      <tr
                        key={p.id}
                        onClick={() => { setSelected(p); setCancelError('') }}
                        className="border-b border-border hover:bg-white/5 transition-colors cursor-pointer"
                      >
                        <td className="px-3 py-2 text-slate-500 text-xs">{payments.length - (startIdx + paged.indexOf(p))}</td>
                        <td className="px-3 py-2 text-slate-400 text-xs max-w-[140px] truncate" title={p.description ?? ''}>
                          {p.description ? p.description.replace('LandUP ', '') : '-'}
                        </td>
                        <td className="px-3 py-2 text-white text-xs font-bold">
                          {p.amount != null ? `${p.amount.toLocaleString()}원` : '-'}
                        </td>
                        <td className="px-3 py-2 text-slate-400 text-xs whitespace-nowrap">{fmtDateOnly(p.createdAt)}</td>
                        <td className={`px-3 py-2 text-slate-400 text-xs whitespace-nowrap ${getNextBillingDisplay(p) === '-' ? 'text-center' : ''}`}>{getNextBillingDisplay(p)}</td>
                        <td className="px-3 py-2 text-xs">
                          {sub
                            ? <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${sub.cls}`}>{sub.label}</span>
                            : <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${STATUS_COLOR[p.status] ?? 'text-slate-400 border-border'}`}>
                                {STATUS_LABEL[p.status] ?? p.status}
                              </span>
                          }
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <Pagination page={payPage} totalPages={totalPages} onChange={setPayPage} />
          </div>
        )
      })()}

      {/* 결제 상세 모달 */}
      {selected && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <span className="text-sm font-bold text-white">결제 상세</span>
              <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-white transition-colors">
                <X size={16} />
              </button>
            </div>

            <div className="px-5 py-4 space-y-3">
              {[
                { label: '결제아이디',   value: `#${selected.id}` },
                { label: '플랜',        value: selected.description ? selected.description.replace('LandUP ', '') : '-' },
                { label: '금액',        value: selected.amount != null ? `${selected.amount.toLocaleString()}원` : '-' },
                { label: '결제일',      value: fmtDateOnly(selected.createdAt) },
                { label: '구독 취소일', value: fmtDateOnly(selected.cancelledAt) },
                { label: '결제방법',    value: selected.method ?? '-' },
                { label: '다음결제일',  value: (() => {
                  if (selected.status === 'cancelled') return '-'
                  if (selected.status === 'success' && !selected.cancelledAt && selected.id !== payments[0]?.id) return '-'
                  return fmtDateOnly(selected.nextBillingDate)
                })() },
                { label: '상태',        value: selected.status === 'cancelled' ? '결제 취소' : selected.status === 'success' ? (selected.cancelledAt ? '구독 취소' : selected.id === payments[0]?.id ? '구독 중' : '이전 플랜') : (STATUS_LABEL[selected.status] ?? selected.status) },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between text-xs">
                  <span className="text-slate-500">{label}</span>
                  <span className="text-white font-medium">{value}</span>
                </div>
              ))}

              {cancelError && (
                <p className="text-xs text-red-400 flex items-center gap-1 pt-1">
                  <AlertCircle size={11} /> {cancelError}
                </p>
              )}
            </div>

            <div className="flex justify-end gap-2 px-5 pb-5">
              <button
                onClick={() => setSelected(null)}
                className="px-4 py-2 text-xs text-white bg-primary hover:bg-primary/80 rounded-lg transition-colors font-bold"
              >
                닫기
              </button>
              {selected.status === 'success' && !selected.cancelledAt && selected.id === payments[0]?.id && (
                <button
                  onClick={() => setShowConfirm(true)}
                  className="px-4 py-2 text-xs text-slate-500 border-b border-border bg-white/5 hover:bg-white/10 border border-border rounded-lg transition-colors"
                >
                  {cancelling ? '취소 중...' : '구독 취소'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 구독 취소 확인 / 완료 모달 */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-xs mx-4 shadow-2xl">
            {cancelDone ? (
              <>
                <div className="px-5 py-5 space-y-2">
                  <p className="text-sm font-bold text-white">구독이 취소되었습니다.</p>
                  <p className="text-xs text-slate-400">{fmtDateOnly(selected?.nextBillingDate)}까지는 현재 플랜을 계속 이용하실 수 있습니다.</p>
                </div>
                <div className="flex justify-end px-5 pb-5">
                  <button
                    onClick={() => { setShowConfirm(false); setCancelDone(false); setSelected(null) }}
                    className="px-4 py-2 text-xs text-white bg-primary hover:bg-primary/80 rounded-lg transition-colors font-bold"
                  >
                    확인
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="px-5 py-5 space-y-2">
                  <p className="text-sm font-bold text-white">구독을 정말 취소하시겠어요?</p>
                  <p className="text-xs text-slate-400">{fmtDateOnly(selected?.nextBillingDate)}까지는 현재 플랜을 계속 이용하실 수 있습니다.</p>
                  {cancelError && (
                    <p className="text-xs text-red-400 flex items-center gap-1 pt-1">
                      <AlertCircle size={11} /> {cancelError}
                    </p>
                  )}
                </div>
                <div className="flex justify-end gap-2 px-5 pb-5">
                  <button
                    onClick={() => { setShowConfirm(false); setCancelError('') }}
                    className="px-4 py-2 text-xs text-slate-300 border-b border-border bg-white/5 hover:bg-white/10 border border-border rounded-lg transition-colors"
                  >
                    돌아가기
                  </button>
                  <button
                    onClick={handleCancel}
                    disabled={cancelling}
                    className="px-4 py-2 text-xs text-red-400 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {cancelling ? '취소 중...' : '구독 취소'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── 크레딧 이력 ────────────────────────────────────────────
const CREDIT_TYPE_LABEL: Record<string, string> = {
  PURCHASE:     '크레딧 구매',
  USE_REDEPLOY: '재배치 사용',
  USE_PROJECT:  '프로젝트 추가',
}
const CREDIT_TYPE_COLOR: Record<string, string> = {
  PURCHASE:     'text-amber-400 bg-amber-400/10 border-amber-400/20',
  USE_REDEPLOY: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
  USE_PROJECT:  'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
}

function CreditSection() {
  const { authLoading } = useAuth()
  const [txs, setTxs] = useState<CreditTransaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creditPage, setCreditPage] = useState(0)
  const [selectedCredit, setSelectedCredit] = useState<CreditTransaction | null>(null)

  useEffect(() => {
    if (authLoading) return
    if (USE_DIRECT) { setLoading(false); return }
    getCreditHistory()
      .then(setTxs)
      .catch(() => setError('크레딧 이력을 불러오는데 실패했습니다.'))
      .finally(() => setLoading(false))
  }, [authLoading])

  return (
    <div className="bg-slate-800 border border-border rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-3 border-b border-border">
        <span className="text-sm font-bold text-white">크레딧 이력</span>
      </div>

      {error && (
        <div className="mx-5 my-4 p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
          <AlertCircle size={13} className="shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-10">
          <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!loading && !error && txs.length === 0 && (
        <p className="text-slate-500 text-xs text-center py-10">크레딧 이력이 없습니다.</p>
      )}

      {/* 크레딧 상세 모달 */}
      {selectedCredit && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-border">
              <span className="text-sm font-bold text-white">크레딧 상세</span>
              <button onClick={() => setSelectedCredit(null)} className="text-slate-400 hover:text-white transition-colors">
                <X size={16} />
              </button>
            </div>
            <div className="px-5 py-4 space-y-3">
              {[
                { label: '구분', value: (
                  <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${CREDIT_TYPE_COLOR[selectedCredit.type] ?? 'text-slate-400 border-border'}`}>
                    {CREDIT_TYPE_LABEL[selectedCredit.type] ?? selectedCredit.type}
                  </span>
                )},
                { label: '크레딧', value: (
                  <span className={`font-bold ${selectedCredit.amount > 0 ? 'text-amber-400' : 'text-red-400'}`}>
                    {selectedCredit.amount > 0 ? `+${selectedCredit.amount}` : selectedCredit.amount} 크레딧
                  </span>
                )},
                { label: '일시', value: fmtDate(selectedCredit.createdAt) },
                { label: '사용 프로젝트', value: selectedCredit.projectName || (selectedCredit.projectId ? `#${selectedCredit.projectId}` : '-') },
              ].map(({ label, value }) => (
                <div key={label} className="flex justify-between items-center text-xs">
                  <span className="text-slate-500">{label}</span>
                  <span className="text-white font-medium">{value}</span>
                </div>
              ))}
            </div>
            <div className="flex justify-end px-5 pb-5">
              <button
                onClick={() => setSelectedCredit(null)}
                className="px-4 py-2 text-xs text-white bg-primary hover:bg-primary/80 rounded-lg transition-colors font-bold"
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && txs.length > 0 && (() => {
        const totalPages = Math.ceil(txs.length / PAGE_SIZE)
        const firstPageSize = txs.length % PAGE_SIZE || PAGE_SIZE
        const startIdx = creditPage === 0 ? 0 : firstPageSize + (creditPage - 1) * PAGE_SIZE
        const paged = txs.slice(startIdx, startIdx + (creditPage === 0 ? firstPageSize : PAGE_SIZE))
        return (
          <div>
            <div className="overflow-x-auto">
              <table className="w-full text-left table-fixed">
                <colgroup>
                  <col className="w-12" />
                  <col className="w-36" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead>
                  <tr className="border-b border-border bg-white/5">
                    {['No.', '구분', '크레딧', '일시'].map(h => (
                      <th key={h} className="px-3 py-2 text-xs text-slate-400 font-bold uppercase tracking-wide whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paged.map((tx, i) => (
                    <tr
                      key={tx.id}
                      onClick={() => setSelectedCredit(tx)}
                      className="border-b border-border hover:bg-white/5 transition-colors cursor-pointer"
                    >
                      <td className="px-3 py-2 text-slate-500 text-xs">{txs.length - (startIdx + i)}</td>
                      <td className="px-3 py-2 text-xs">
                        <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold ${CREDIT_TYPE_COLOR[tx.type] ?? 'text-slate-400 border-border'}`}>
                          {CREDIT_TYPE_LABEL[tx.type] ?? tx.type}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs font-bold text-white">
                        {tx.amount > 0 ? `+${tx.amount}` : tx.amount} 크레딧
                      </td>
                      <td className="px-3 py-2 text-slate-400 text-xs whitespace-nowrap">{fmtDateOnly(tx.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={creditPage} totalPages={totalPages} onChange={setCreditPage} />
          </div>
        )
      })()}
    </div>
  )
}

// ── 메인 ───────────────────────────────────────────────────
export default function MyPage() {
  const { currentUser } = useAuth()
  const navigate = useNavigate()
  return (
    <main className="flex-1 flex flex-col px-6 py-8">
      <div className="max-w-5xl w-full mx-auto space-y-6">
        <div>
          <h2 className="text-2xl font-bold text-white mb-1">마이페이지</h2>
          {currentUser && (
            <p className="text-xs text-slate-400">
              <span className="text-white font-medium">{currentUser.name}</span> 님 ·{' '}
              멤버십 <span className="text-accent capitalize">{currentUser.membership}</span>
            </p>
          )}
        </div>
        <UserInfoSection />
        <PlanLimitSection />
        <PaymentsSection />
        <CreditSection />
      </div>
    </main>
  )
}
