import { useState } from "react"
import { naverLoginUrl } from "../lib/naverAuth"
import { kakaoLoginUrl } from "../lib/kakaoAuth"
import { googleLoginUrl } from "../lib/googleAuth"
import { API_BASE } from "../lib/axiosClient"

// 환경변수 빈 값일 때 OAuth 회원가입 버튼 자동 숨김 (Login.tsx 와 동일 패턴).
const SHOW_NAVER  = !!import.meta.env.VITE_NAVER_CLIENT_ID
const SHOW_KAKAO  = !!import.meta.env.VITE_KAKAO_REST_API_KEY
const SHOW_GOOGLE = !!import.meta.env.VITE_GOOGLE_CLIENT_ID

// ── 키보드 연속 패턴 ──────────────────────────────────────────────────
const KEYBOARD_SEQUENCES = [
  "qwertyuiop", "asdfghjkl", "zxcvbnm",
  "1234567890", "0987654321",
  "abcdefghijklmnopqrstuvwxyz",
]

interface PasswordCheck {
  label: string
  ok: boolean
  warn?: boolean  // 권장 사항 (필수 아님)
}

function checkPassword(pw: string): PasswordCheck[] {
  const hasLower = /[a-z]/.test(pw)
  const hasNumber = /[0-9]/.test(pw)
  const hasSpecial = /[!@#$%^&*()\-_=+\[\]{};:'",.<>/?\\|`~]/.test(pw)

  // 같은 문자 3회 이상 연속
  const hasRepeat = /(.)\1{2,}/.test(pw)

  // 키보드 연속 패턴 (3자 이상 부분 문자열)
  const lower = pw.toLowerCase()
  const hasKeyboardSeq = KEYBOARD_SEQUENCES.some(seq => {
    for (let i = 0; i <= seq.length - 3; i++) {
      const sub = seq.slice(i, i + 3)
      if (lower.includes(sub)) return true
    }
    return false
  })

  return [
    { label: "8자 이상", ok: pw.length >= 8 },
    { label: "12자 이상 (권장)", ok: pw.length >= 12, warn: true },
    { label: "영문 소문자 포함", ok: hasLower },
    { label: "숫자 포함", ok: hasNumber },
    { label: "특수문자 포함", ok: hasSpecial },
    { label: "같은 문자 3회 연속 없음", ok: !hasRepeat },
    { label: "키보드 연속 패턴 없음", ok: !hasKeyboardSeq },
  ]
}

function validatePassword(pw: string): string | null {
  const checks = checkPassword(pw)
  const failed = checks.filter(c => !c.warn && !c.ok)
  if (failed.length === 0) return null
  return failed[0].label + " 조건을 충족하지 않습니다."
}

interface SignUpForm {
  name: string
  phone: string
  email: string
  password: string
  passwordConfirm: string
}

interface Props {
  onSuccess: (email: string) => void
  onLoginClick: () => void
}

export default function SignUp({ onSuccess, onLoginClick }: Props) {
  const [form, setForm] = useState<SignUpForm>({
    name: "", phone: "", email: "", password: "", passwordConfirm: "",
  })
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)
  const [pwFocused, setPwFocused] = useState(false)  // eslint-disable-line

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    let value = e.target.value
    // 전화번호: 숫자만 허용 (TR_D 4-28 [회원가입_전화번호_비숫자허용] fix)
    if (e.target.name === "phone") {
      value = value.replace(/\D/g, "")
    }
    setForm(prev => ({ ...prev, [e.target.name]: value }))
    setError("")
  }

  const validate = (): string => {
    if (!form.name.trim()) return "이름을 입력해주세요."
    if (!/^01[0-9]{8,9}$/.test(form.phone)) return "올바른 전화번호를 입력해주세요. (예: 01012345678)"
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) return "올바른 이메일 형식을 입력해주세요."
    const pwError = validatePassword(form.password)
    if (pwError) return pwError
    if (form.password !== form.passwordConfirm) return "비밀번호가 일치하지 않습니다."
    return ""
  }

  const pwChecks = checkPassword(form.password)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const validationError = validate()
    if (validationError) { setError(validationError); return }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: 'include',
        body: JSON.stringify({
          name: form.name,
          phone: form.phone,
          email: form.email,
          password: form.password,
        }),
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || "회원가입에 실패했습니다.")
        return
      }
      const data = await res.json()
      onSuccess(data.email)
    } catch {
      setError("서버와 연결할 수 없습니다.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">

        {/* 로고 */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">LandUP</h1>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-white mb-6">회원가입</h2>

          {/* ── 소셜 회원가입 버튼들 (환경변수 등록된 것만 노출) ── */}
          {SHOW_KAKAO && (
            <button
              type="button"
              onClick={() => { const url = kakaoLoginUrl(); if (url) window.location.href = url }}
              className="w-full flex items-center justify-center gap-2.5 bg-[#FEE500] hover:bg-[#fdd800] text-[#000000D9] font-bold rounded-lg py-2.5 text-sm transition mb-2"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 3C6.477 3 2 6.477 2 10.8c0 2.796 1.85 5.247 4.627 6.623-.204.76-.739 2.759-.847 3.187-.133.53.195.524.41.381.167-.111 2.665-1.812 3.746-2.548.666.099 1.35.151 2.064.151 5.523 0 10-3.477 10-7.794S17.523 3 12 3z" />
              </svg>
              카카오로 회원가입
            </button>
          )}

          {SHOW_GOOGLE && (
            <button
              type="button"
              onClick={() => { const url = googleLoginUrl(); if (url) window.location.href = url }}
              className="w-full flex items-center justify-center gap-2.5 bg-white hover:bg-slate-100 text-slate-800 font-bold rounded-lg py-2.5 text-sm transition mb-2 border border-slate-300"
            >
              <svg width="18" height="18" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
              </svg>
              구글로 회원가입
            </button>
          )}

          {SHOW_NAVER && (
            <button
              type="button"
              onClick={() => { const url = naverLoginUrl(); if (url) window.location.href = url }}
              className="w-full flex items-center justify-center gap-2.5 bg-[#03C75A] hover:bg-[#02b350] text-white font-bold rounded-lg py-2.5 text-sm transition mb-4"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
                <path d="M16.273 12.845L7.376 0H0v24h7.727V11.155L16.624 24H24V0h-7.727z" />
              </svg>
              네이버 아이디로 회원가입
            </button>
          )}

          {/* 구분선 — 소셜 버튼이 하나라도 있을 때만 표시 */}
          {(SHOW_KAKAO || SHOW_GOOGLE || SHOW_NAVER) && (
            <div className="flex items-center gap-3 mb-4 mt-2">
              <div className="flex-1 h-px bg-slate-700/60" />
              <span className="text-xs text-slate-600">또는 이메일로 가입</span>
              <div className="flex-1 h-px bg-slate-700/60" />
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* 이름 */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">이름</label>
              <input
                name="name"
                type="text"
                placeholder="홍길동"
                value={form.name}
                onChange={handleChange}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            {/* 전화번호 */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">전화번호</label>
              <input
                name="phone"
                type="tel"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={11}
                placeholder="01012345678"
                value={form.phone}
                onChange={handleChange}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            {/* 이메일 */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">이메일</label>
              <input
                name="email"
                type="email"
                placeholder="example@email.com"
                value={form.email}
                onChange={handleChange}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            {/* 비밀번호 */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">비밀번호</label>
              <input
                name="password"
                type="password"
                placeholder="8자 이상 입력"
                value={form.password}
                onChange={handleChange}
                onFocus={() => setPwFocused(true)}
                onBlur={() => setPwFocused(false)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
              {/* 비밀번호 조건 체크리스트 */}
              {form.password.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {pwChecks.map(({ label, ok, warn }) => (
                    <li key={label} className={`flex items-center gap-1.5 text-xs ${ok
                        ? warn ? "text-yellow-400" : "text-emerald-400"
                        : "text-slate-500"
                      }`}>
                      <span>{ok ? "✓" : "✗"}</span>
                      <span>{label}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* 비밀번호 확인 */}
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">비밀번호 확인</label>
              <input
                name="passwordConfirm"
                type="password"
                placeholder="비밀번호를 다시 입력"
                value={form.passwordConfirm}
                onChange={handleChange}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
              {/* 비밀번호 불일치 실시간 안내 (TR_D 4-28 [회원가입_비번불일치_안내부재] fix) */}
              {form.passwordConfirm.length > 0 && form.password !== form.passwordConfirm && (
                <p className="mt-1.5 text-xs text-red-400">비밀번호가 일치하지 않습니다.</p>
              )}
            </div>

            {/* 에러 메시지 */}
            {error && (
              <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/30 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            {/* 제출 버튼 */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg py-2.5 text-sm transition mt-2"
            >
              {loading ? "처리 중..." : "회원가입"}
            </button>
          </form>

          <p className="text-center text-xs text-slate-500 mt-5">
            이미 계정이 있으신가요?{" "}
            <button
              onClick={onLoginClick}
              className="text-indigo-400 hover:text-indigo-300 transition"
            >
              로그인
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
