import { useState } from "react"
import { naverLoginUrl } from "../lib/naverAuth"
import { kakaoLoginUrl } from "../lib/kakaoAuth"
import { googleLoginUrl } from "../lib/googleAuth"
import { API_BASE } from "../lib/axiosClient"

interface Props {
  onSuccess: (user: { id: number; name: string; email: string; membership: string; accessToken: string }) => void
  onVerificationRequired: (email: string) => void
  onSignUpClick: () => void
}

export default function Login({ onSuccess, onVerificationRequired, onSignUpClick }: Props) {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) { setError("이메일과 비밀번호를 입력해주세요."); return }
    // 이메일 형식 검증 (TR_D 4-28 [로그인_이메일형식검증_누락] fix)
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError("올바른 이메일 형식이 아닙니다.")
      return
    }

    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || "로그인에 실패했습니다.")
        return
      }
      const user = await res.json()
      // 이메일 미인증 — 메일 재발송 + /auth/email-sent 로 이동
      if ((user.requiresVerification ?? user.requires_verification) && !(user.accessToken ?? user.access_token)) {
        onVerificationRequired(user.email)
        return
      }
      onSuccess(user)
    } catch {
      setError("서버와 연결할 수 없습니다.")
    } finally {
      setLoading(false)
    }
  }

  const handleNaverLogin = () => {
    window.location.href = naverLoginUrl()
  }

  const handleKakaoLogin = () => {
    const url = kakaoLoginUrl()
    if (url) window.location.href = url
  }

  const handleGoogleLogin = () => {
    const url = googleLoginUrl()
    if (url) window.location.href = url
  }

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">

        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">LandUP</h1>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-white mb-6">로그인</h2>

          {/* ── 소셜 로그인 버튼들 ── */}
          {/* 카카오 로그인  */}
          <button
            onClick={handleKakaoLogin}
            className="w-full flex items-center justify-center gap-2.5 bg-[#FEE500] hover:bg-[#fdd800] text-[#000000D9] font-bold rounded-lg py-2.5 text-sm transition mb-2"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 3C6.477 3 2 6.477 2 10.8c0 2.796 1.85 5.247 4.627 6.623-.204.76-.739 2.759-.847 3.187-.133.53.195.524.41.381.167-.111 2.665-1.812 3.746-2.548.666.099 1.35.151 2.064.151 5.523 0 10-3.477 10-7.794S17.523 3 12 3z" />
            </svg>
            카카오로 로그인
          </button>

          {/* 구글 로그인 */}
          <button
            onClick={handleGoogleLogin}
            className="w-full flex items-center justify-center gap-2.5 bg-white hover:bg-slate-100 text-slate-800 font-bold rounded-lg py-2.5 text-sm transition mb-2 border border-slate-300"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            구글로 로그인
          </button>

          {/* 네이버 로그인 버튼 */}
          <button
            onClick={handleNaverLogin}
            className="w-full flex items-center justify-center gap-2.5 bg-[#03C75A] hover:bg-[#02b350] text-white font-bold rounded-lg py-2.5 text-sm transition mb-4"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="white">
              <path d="M16.273 12.845L7.376 0H0v24h7.727V11.155L16.624 24H24V0h-7.727z" />
            </svg>
            네이버 아이디로 로그인
          </button>

          {/* 구분선 */}
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-px bg-slate-700/60" />
            <span className="text-xs text-slate-600">또는</span>
            <div className="flex-1 h-px bg-slate-700/60" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">이메일</label>
              <input
                type="email"
                placeholder="example@email.com"
                value={email}
                onChange={e => { setEmail(e.target.value); setError("") }}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">비밀번호</label>
              <input
                type="password"
                placeholder="비밀번호 입력"
                value={password}
                onChange={e => { setPassword(e.target.value); setError("") }}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            {error && (
              <p className="text-red-400 text-xs bg-red-900/20 border border-red-800/30 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-medium rounded-lg py-2.5 text-sm transition mt-2"
            >
              {loading ? "로그인 중..." : "로그인"}
            </button>
          </form>

          <p className="text-center text-xs text-slate-500 mt-5">
            계정이 없으신가요?{" "}
            <button
              onClick={onSignUpClick}
              className="text-indigo-400 hover:text-indigo-300 transition"
            >
              회원가입
            </button>
          </p>
        </div>
      </div>
    </div>
  )
}
