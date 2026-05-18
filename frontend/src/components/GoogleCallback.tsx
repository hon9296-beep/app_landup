import { useEffect, useRef, useState } from "react"
import { parseGoogleCallback, validateGoogleState } from "../lib/googleAuth"
import { API_BASE } from "../lib/axiosClient"

interface OAuthUser {
  id: number; name: string; email: string; membership: string;
  accessToken: string | null; requiresVerification?: boolean;
}

interface Props {
  onSuccess: (user: OAuthUser) => void
  onVerificationRequired: (user: OAuthUser) => void
  onError: () => void
}

export default function GoogleCallback({ onSuccess, onVerificationRequired, onError }: Props) {
  const [msg, setMsg] = useState("구글 로그인 처리 중...")
  const called = useRef(false)  // StrictMode 이중 실행 방지

  useEffect(() => {
    if (called.current) return
    called.current = true

    const parsed = parseGoogleCallback()
    if (!parsed) { setMsg("잘못된 접근입니다."); setTimeout(onError, 1500); return }

    if (!validateGoogleState(parsed.state)) {
      setMsg("보안 검증 실패. 다시 시도해주세요.")
      setTimeout(onError, 1500)
      return
    }

    fetch(`${API_BASE}/auth/google/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: 'include',
      body: JSON.stringify({
        code: parsed.code,
        state: parsed.state,
        redirectUri: `${window.location.origin}/google/callback`,
      }),
    })
      .then(res => {
        if (!res.ok) return res.json().then(d => Promise.reject(d.detail || "로그인 실패"))
        return res.json()
      })
      .then(user => {
        if (user.requiresVerification) {
          onVerificationRequired(user)
        } else {
          onSuccess(user)
        }
      })
      .catch(err => {
        setMsg(typeof err === "string" ? err : "구글 로그인에 실패했습니다.")
        setTimeout(onError, 2000)
      })
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center">
        <div className="w-10 h-10 border-2 border-[#4285F4] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-300 text-sm">{msg}</p>
      </div>
    </div>
  )
}
