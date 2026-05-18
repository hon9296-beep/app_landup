import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Pencil, Check, X, AlertCircle, ChevronLeft, ChevronRight, ChevronDown, Search } from 'lucide-react'
import axiosClient from '../../lib/axiosClient'

interface PaymentRow {
  id: number
  amount: number
  createdAt: string
  cancelledAt: string | null
  description: string | null
  method: string | null
  nextBillingDate: string | null
  status: string
}

interface UserRow {
  id: number
  name: string
  phone: string | null
  email: string
  membership: string
  createdAt: string
  isVerified: boolean
  authMethod: string
  payments: PaymentRow[]
}

interface PageResponse {
  content: UserRow[]
  totalElements: number
  totalPages: number
  number: number
}

const PAGE_SIZE = 10
const STATUS_OPTIONS = ['pending', 'success', 'failed', 'cancelled']
const STATUS_LABEL: Record<string, string> = {
  pending: '대기', success: '성공', failed: '실패', cancelled: '취소',
}
const STATUS_COLOR: Record<string, string> = {
  pending:   'text-amber-400 bg-amber-400/10 border-amber-400/20',
  success:   'text-accent bg-accent/20 border-accent/30',
  failed:    'text-red-400 bg-red-500/10 border-red-500/30',
  cancelled: 'text-slate-400 bg-white/5 border-border',
}

function fmtDate(dt: string | null) {
  if (!dt) return '-'
  const d = new Date(dt)
  const y = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const h = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${y}.${mo}.${day} ${h}:${min}`
}

function fmtDateOnly(dt: string | null) {
  if (!dt) return '-'
  const d = new Date(dt)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}.${m}.${day}`
}

function toInputDate(dt: string | null): string {
  if (!dt) return ''
  const d = new Date(dt)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ── 인라인 에러 ──────────────────────────────────────────────────────────
function InlineError({ msg }: { msg: string }) {
  return (
    <div className="flex gap-1.5 items-center mt-1 px-2 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">
      <AlertCircle size={11} className="shrink-0" />
      {msg}
    </div>
  )
}

// ── 결제 행 ────────────────────────────────────────────────────────────
function PaymentItem({
  payment,
  onSaved,
}: {
  payment: PaymentRow
  onSaved: (p: PaymentRow) => void
}) {
  const [editing, setEditing] = useState(false)
  const [status, setStatus] = useState(payment.status)
  const [nextBilling, setNextBilling] = useState(toInputDate(payment.nextBillingDate))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  const save = async () => {
    setSaving(true); setError('')
    try {
      const res = await axiosClient.patch(`/admin/payments/${payment.id}`, {
        status,
        nextBillingDate: nextBilling ? `${nextBilling}T00:00:00` : null,
      })
      onSaved(res.data)
      setEditing(false)
    } catch { setError('저장에 실패했습니다.') }
    finally { setSaving(false) }
  }

  const cancel = () => {
    setStatus(payment.status)
    setNextBilling(toInputDate(payment.nextBillingDate))
    setEditing(false); setError('')
  }

  const handleCancelPayment = async () => {
    setCancelling(true); setError('')
    try {
      const res = await axiosClient.post(`/admin/payments/${payment.id}/cancel`, { reason: '관리자 환불' })
      onSaved(res.data)
      setShowCancelConfirm(false)
    } catch { setError('결제 취소에 실패했습니다.') }
    finally { setCancelling(false) }
  }

  return (
    <>
      <tr className="border-b border-border hover:bg-white/5 transition-colors">
        <td className="px-3 py-2 text-slate-500 text-xs">#{payment.id}</td>
        <td className="px-3 py-2 text-white text-xs font-bold">
          {payment.amount != null ? `${payment.amount.toLocaleString()}원` : '-'}
        </td>
        <td className="px-3 py-2 text-slate-400 text-xs whitespace-nowrap">{fmtDate(payment.createdAt)}</td>
        <td className="px-3 py-2 text-slate-400 text-xs whitespace-nowrap">{fmtDate(payment.cancelledAt)}</td>
        <td className="px-3 py-2 text-slate-400 text-xs max-w-[140px] truncate" title={payment.description ?? ''}>
          {payment.description || '-'}
        </td>
        <td className="px-3 py-2 text-slate-400 text-xs">{payment.method ?? '-'}</td>
        <td className="px-3 py-2 text-xs w-[130px]">
          {editing ? (
            <input
              type="date"
              value={nextBilling}
              onChange={e => setNextBilling(e.target.value)}
              className="bg-slate-800 border border-border rounded-lg px-2 py-1 text-white text-xs w-full focus:outline-none focus:border-primary transition-colors"
            />
          ) : (
            <span className="text-slate-400 whitespace-nowrap">{fmtDateOnly(payment.nextBillingDate)}</span>
          )}
        </td>
        <td className="px-3 py-2 text-xs w-[96px]">
          {editing ? (
            <select
              value={status}
              onChange={e => setStatus(e.target.value)}
              className="bg-slate-800 border border-border rounded-lg px-2 py-1 text-white text-xs w-full focus:outline-none focus:border-primary transition-colors"
            >
              {STATUS_OPTIONS.map(s => (
                <option key={s} value={s}>{STATUS_LABEL[s]}</option>
              ))}
            </select>
          ) : (
            <span className={`px-2 py-0.5 rounded-full text-xs border ${STATUS_COLOR[payment.status] ?? 'text-slate-400 border-border'}`}>
              {STATUS_LABEL[payment.status] ?? payment.status}
            </span>
          )}
        </td>
        <td className="px-3 py-2">
          <div className="flex items-center gap-1">
            {editing ? (
              <>
                <button onClick={save} disabled={saving}
                  className="p-1.5 rounded-lg text-accent hover:bg-accent/20 transition-colors disabled:opacity-50">
                  <Check size={13} />
                </button>
                <button onClick={cancel}
                  className="p-1.5 rounded-lg text-slate-300 bg-white/5 hover:bg-white/10 border border-border transition-colors">
                  <X size={13} />
                </button>
              </>
            ) : (
              <>
                {payment.status === 'success' && (
                  <button
                    onClick={() => setShowCancelConfirm(true)}
                    className="px-2 py-1 text-[10px] font-bold rounded-lg text-red-400 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 transition-colors"
                  >
                    결제취소
                  </button>
                )}
              </>
            )}
          </div>
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={9} className="px-3 pb-2">
            <InlineError msg={error} />
          </td>
        </tr>
      )}

      {/* 결제 취소 확인 모달 */}
      {showCancelConfirm && (
        <tr>
          <td colSpan={9}>
            <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
              <div className="bg-slate-800 border border-border rounded-2xl w-full max-w-sm mx-4 shadow-2xl">
                <div className="px-5 py-5 space-y-2">
                  <p className="text-sm font-bold text-white">결제를 취소하시겠어요?</p>
                  <p className="text-xs text-slate-400">
                    결제를 취소하면 즉시 환불 처리됩니다. 이 작업은 취소할 수 없습니다.
                  </p>
                  {error && <p className="text-xs text-red-400 pt-1">{error}</p>}
                </div>
                <div className="flex justify-end gap-2 px-5 pb-5">
                  <button
                    onClick={() => { setShowCancelConfirm(false); setError('') }}
                    className="px-4 py-2 text-xs text-slate-300 bg-white/5 hover:bg-white/10 border border-border rounded-lg transition-colors"
                  >
                    돌아가기
                  </button>
                  <button
                    onClick={handleCancelPayment}
                    disabled={cancelling}
                    className="px-4 py-2 text-xs font-bold text-red-400 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {cancelling ? '처리 중...' : '환불 확인'}
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

// ── 회원 블록 ─────────────────────────────────────────────────────────
function UserBlock({
  user: init,
  no,
  isExpanded,
  onToggleExpand,
}: {
  user: UserRow
  no: number
  isExpanded: boolean
  onToggleExpand: () => void
}) {
  const [user, setUser] = useState(init)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(init.name)
  const [phone, setPhone] = useState(init.phone ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isExpanded && editing) {
      setEditing(false)
      setName(user.name)
      setPhone(user.phone ?? '')
      setError('')
    }
  }, [isExpanded])

  const saveUser = async () => {
    setSaving(true); setError('')
    try {
      const res = await axiosClient.patch(`/admin/users/${user.id}`, {
        name, phone: phone || null,
      })
      setUser(res.data)
      setEditing(false)
    } catch { setError('저장에 실패했습니다.') }
    finally { setSaving(false) }
  }

  const cancelUser = () => {
    setName(user.name); setPhone(user.phone ?? '')
    setEditing(false); setError('')
  }

  const handlePaymentSaved = (updated: PaymentRow) => {
    setUser(prev => ({
      ...prev,
      payments: prev.payments.map(p => p.id === updated.id ? updated : p),
    }))
  }

  const toggleExpand = () => {
    if (editing) return
    onToggleExpand()
  }

  return (
    <div className={`border-b border-border last:border-b-0 ${isExpanded ? 'bg-slate-900/40' : ''}`}>
      {/* 요약 행 — 항상 동일한 그리드 유지 */}
      <div
        className={`grid grid-cols-[60px_1.5fr_1fr_2fr_0.8fr_1fr_1fr_0.9fr_56px] gap-6 px-4 py-3 items-center transition-colors ${!editing ? 'cursor-pointer hover:bg-white/5' : ''}`}
        onClick={toggleExpand}
      >
        <span className="text-slate-500 text-xs">{no}</span>

        {/* 이름 */}
        {editing ? (
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            onClick={e => e.stopPropagation()}
            className="bg-slate-700 border border-primary rounded-lg px-2 py-1 text-white text-xs font-bold focus:outline-none w-full"
            placeholder="이름"
          />
        ) : (
          <span className="text-white text-xs font-bold truncate">{user.name}</span>
        )}

        {/* 전화번호 */}
        {editing ? (
          <input
            value={phone}
            onChange={e => setPhone(e.target.value)}
            onClick={e => e.stopPropagation()}
            className="bg-slate-700 border border-primary rounded-lg px-2 py-1 text-white text-xs focus:outline-none w-full"
            placeholder="전화번호"
          />
        ) : (
          <span className="text-slate-400 text-xs truncate">{user.phone ?? '-'}</span>
        )}

        <span className="text-slate-400 text-xs truncate">{user.email}</span>
        <span className="text-primary text-[11px] font-bold">{user.membership}</span>
        <span className={`text-[11px] font-medium ${user.isVerified ? 'text-accent' : 'text-amber-400'}`}>
          {user.isVerified ? '인증완료' : '미완료'}
        </span>
        <span className="text-slate-400 text-[11px] truncate">{user.authMethod || '-'}</span>
        <span className="text-slate-400 text-[11px] whitespace-nowrap">{fmtDateOnly(user.createdAt)}</span>

        {/* 우측 버튼 영역 */}
        <div className="flex items-center justify-end gap-1" onClick={e => e.stopPropagation()}>
          {isExpanded && (
            editing ? (
              <>
                <button onClick={saveUser} disabled={saving}
                  className="p-1.5 rounded-lg text-accent hover:bg-accent/20 transition-colors disabled:opacity-50">
                  <Check size={13} />
                </button>
                <button onClick={cancelUser}
                  className="p-1.5 rounded-lg text-slate-400 hover:bg-white/10 border border-border transition-colors">
                  <X size={13} />
                </button>
              </>
            ) : (
              <button onClick={() => setEditing(true)}
                className="p-1.5 rounded-lg text-slate-500 hover:text-primary hover:bg-primary/10 transition-colors">
                <Pencil size={13} />
              </button>
            )
          )}
          <button onClick={toggleExpand} className="p-1.5 text-slate-500">
            <ChevronDown size={14} className={`transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`} />
          </button>
        </div>
      </div>

      {/* 인라인 에러 */}
      {isExpanded && error && (
        <div className="px-4 pb-2">
          <InlineError msg={error} />
        </div>
      )}

      {/* 결제 내역 — 행 바로 아래 자연스럽게 연결 */}
      {isExpanded && (
        <div className="border-t border-border overflow-x-auto">
          {user.payments.length === 0 ? (
            <p className="px-4 py-3 text-slate-500 text-xs">결제 내역 없음</p>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border bg-white/5">
                  {['결제아이디', '금액', '결제일자', '결제취소일자', '설명', '결제방법', '다음결제일', '상태', ''].map(h => (
                    <th key={h} className="px-3 py-2 text-[10px] text-slate-500 font-bold uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {user.payments.map(p => (
                  <PaymentItem key={p.id} payment={p} onSaved={handlePaymentSaved} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// ── 페이지네이션 ────────────────────────────────────────────────────────
function Pagination({
  page, totalPages, onChange,
}: {
  page: number; totalPages: number; onChange: (p: number) => void
}) {
  if (totalPages <= 1) return null

  // 최대 5개 페이지 버튼 표시
  const range: number[] = []
  const delta = 2
  const left = Math.max(0, page - delta)
  const right = Math.min(totalPages - 1, page + delta)
  for (let i = left; i <= right; i++) range.push(i)

  return (
    <div className="flex items-center justify-center gap-1.5 pt-4">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page === 0}
        className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <ChevronLeft size={14} />
      </button>

      {left > 0 && (
        <>
          <button onClick={() => onChange(0)}
            className="w-8 h-8 rounded-lg text-xs bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors">
            1
          </button>
          {left > 1 && <span className="text-slate-600 text-xs px-1">…</span>}
        </>
      )}

      {range.map(i => (
        <button
          key={i}
          onClick={() => onChange(i)}
          className={`w-8 h-8 rounded-lg text-xs font-bold transition-colors ${
            i === page
              ? 'bg-primary text-white'
              : 'bg-white/5 hover:bg-white/10 border border-border text-slate-300'
          }`}
        >
          {i + 1}
        </button>
      ))}

      {right < totalPages - 1 && (
        <>
          {right < totalPages - 2 && <span className="text-slate-600 text-xs px-1">…</span>}
          <button onClick={() => onChange(totalPages - 1)}
            className="w-8 h-8 rounded-lg text-xs bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors">
            {totalPages}
          </button>
        </>
      )}

      <button
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages - 1}
        className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-border text-slate-300 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <ChevronRight size={14} />
      </button>
    </div>
  )
}

// ── 메인 페이지 ─────────────────────────────────────────────────────────
export default function AdminUserPage() {
  const navigate = useNavigate()
  const [users, setUsers] = useState<UserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [totalElements, setTotalElements] = useState(0)
  const [expandedUserId, setExpandedUserId] = useState<number | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchUsers = (p: number, q: string) => {
    setLoading(true)
    setFetchError('')
    axiosClient.get('/admin/users', { params: { page: p, size: PAGE_SIZE, search: q } })
      .then(res => {
        const data: PageResponse = res.data
        setUsers(data.content)
        setTotalPages(data.totalPages)
        setTotalElements(data.totalElements)
      })
      .catch(() => setFetchError('회원 목록을 불러오는데 실패했습니다.'))
      .finally(() => setLoading(false))
  }

  // 마운트 시 초기 조회
  useEffect(() => {
    fetchUsers(0, '')
  }, [])

  // 검색어 변경 시 디바운스 300ms 후 page=0 으로 재조회
  const handleSearchChange = (value: string) => {
    setSearch(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setPage(0)
      fetchUsers(0, value)
    }, 300)
  }

  // 페이지 변경 시 즉시 재조회
  const handlePageChange = (p: number) => {
    setPage(p)
    setExpandedUserId(null)
    fetchUsers(p, search)
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <header className="flex items-center gap-3 px-6 py-3 border-b border-border shrink-0">
        <button onClick={() => navigate('/admin')}
          className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft size={18} />
        </button>
        <span className="text-white font-semibold">회원정보 조회 및 수정</span>
        {!loading && (
          <span className="text-slate-500 text-xs ml-1">
            (총 {totalElements}명)
          </span>
        )}
      </header>

      <main className="flex-1 px-6 py-6">
        <div className="max-w-6xl mx-auto space-y-4">

          {/* 검색 */}
          <div className="relative mb-2">
            <input
              type="text"
              placeholder="이름, 이메일, 전화번호 검색..."
              value={search}
              onChange={e => handleSearchChange(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { if (debounceRef.current) clearTimeout(debounceRef.current); setPage(0); fetchUsers(0, search) } }}
              className="w-full bg-slate-800 border border-border rounded-xl px-4 py-2.5 pr-12 text-sm
                         text-white placeholder-slate-500 focus:outline-none focus:border-primary transition-colors"
            />
            <button
              onClick={() => { if (debounceRef.current) clearTimeout(debounceRef.current); setPage(0); fetchUsers(0, search) }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white transition-colors"
            >
              <Search size={16} />
            </button>
          </div>

          {/* 전역 에러 */}
          {fetchError && (
            <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded-xl text-xs text-red-400 flex gap-2">
              <AlertCircle size={13} className="shrink-0 mt-0.5" />
              {fetchError}
            </div>
          )}

          {/* 컬럼 가이드 */}
          {!loading && !fetchError && users.length > 0 && (
            <div className="grid grid-cols-[60px_1.5fr_1fr_2fr_0.8fr_1fr_1fr_0.9fr_56px] gap-6 px-4 py-2.5
                            bg-slate-800 border border-border rounded-xl
                            text-sm text-slate-300 font-bold tracking-wide">
              <span>No.</span>
              <span>이름</span>
              <span>전화번호</span>
              <span>이메일</span>
              <span>멤버십</span>
              <span>이메일 인증</span>
              <span>인증방법</span>
              <span>가입일</span>
              <span />
            </div>
          )}

          {/* 로딩 */}
          {loading && (
            <div className="flex justify-center py-16">
              <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {/* 빈 상태 */}
          {!loading && !fetchError && users.length === 0 && (
            <p className="text-slate-500 text-sm text-center py-8">
              {search ? '검색 결과가 없습니다.' : '회원이 없습니다.'}
            </p>
          )}

          {/* 회원 목록 */}
          {!loading && users.length > 0 && (
            <div className="bg-slate-800 border border-border rounded-xl overflow-hidden">
              {users.map((u, idx) => (
                <UserBlock
                  key={u.id}
                  user={u}
                  no={totalElements - (page * PAGE_SIZE + idx)}
                  isExpanded={expandedUserId === u.id}
                  onToggleExpand={() => setExpandedUserId(prev => prev === u.id ? null : u.id)}
                />
              ))}
            </div>
          )}

          {/* 페이지네이션 */}
          {!loading && !fetchError && (
            <Pagination page={page} totalPages={totalPages} onChange={handlePageChange} />
          )}
        </div>
      </main>
    </div>
  )
}
