import { useState } from "react"
import { API_BASE } from "../lib/axiosClient"

interface Props {
  userId: number
  /** 카카오 callback 응답에서 받은 5분 단기 토큰 — profile/complete 보안 hole 차단용. */
  profileToken?: string
  initialName?: string
  initialEmail?: string
  onSuccess: (user: { id: number; name: string; email: string; membership: string; accessToken: string | null; requiresVerification?: boolean }) => void
  onError: () => void
}

export default function KakaoProfileCompletion({ userId, profileToken, initialName, initialEmail, onSuccess, onError }: Props) {
  const [name, setName] = useState(initialName || "")
  const [phone, setPhone] = useState("")
  const [email, setEmail] = useState(initialEmail?.endsWith("@kakao.local") ? "" : (initialEmail || ""))
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError("이름을 입력해주세요."); return }
    if (!email.trim()) { setError("이메일을 입력해주세요."); return }

    setLoading(true)
    setError("")
    try {
      const res = await fetch(`${API_BASE}/auth/profile/complete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: 'include',
        body: JSON.stringify({ userId, name, phone: phone || null, email, profileToken }),
      })
      if (!res.ok) {
        const data = await res.json()
        setError(data.detail || "저장에 실패했습니다.")
        return
      }
      const user = await res.json()
      onSuccess(user)
    } catch {
      setError("서버와 연결할 수 없습니다.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">LandUP</h1>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-white mb-2">추가 정보 입력</h2>
          <p className="text-slate-400 text-sm mb-6">카카오 로그인이 완료되었습니다. 서비스 이용을 위해 정보를 입력해주세요.</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">이름 <span className="text-red-400">*</span></label>
              <input
                type="text"
                placeholder="이름 입력"
                value={name}
                onChange={e => { setName(e.target.value); setError("") }}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">전화번호</label>
              <input
                type="tel"
                placeholder="01012345678 (선택)"
                value={phone}
                onChange={e => { setPhone(e.target.value); setError("") }}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">이메일 <span className="text-red-400">*</span></label>
              <input
                type="email"
                placeholder="example@email.com"
                value={email}
                onChange={e => { setEmail(e.target.value); setError("") }}
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
              {loading ? "저장 중..." : "저장하고 시작하기"}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
