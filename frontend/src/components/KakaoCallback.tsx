import { useEffect, useRef, useState } from "react"
import { parseKakaoCallback, validateKakaoState } from "../lib/kakaoAuth"
import { API_BASE } from "../lib/axiosClient"

interface KakaoUser {
  id: number; name: string; email: string; membership: string;
  accessToken: string | null; requiresProfileCompletion?: boolean; requiresVerification?: boolean;
  /** 프로필 미완성 응답에만 포함 (5분 단기 토큰) — profile/complete 호출 시 함께 전송. */
  profileToken?: string;
}

interface Props {
  onSuccess: (user: KakaoUser) => void
  onProfileRequired: (user: KakaoUser) => void
  onVerificationRequired: (user: KakaoUser) => void
  onError: () => void
}

export default function KakaoCallback({ onSuccess, onProfileRequired, onVerificationRequired, onError }: Props) {
  const [msg, setMsg] = useState("카카오 로그인 처리 중...")
  const called = useRef(false)

  useEffect(() => {
    if (called.current) return
    called.current = true

    const parsed = parseKakaoCallback()
    if (!parsed) { setMsg("잘못된 접근입니다."); setTimeout(onError, 1500); return }

    if (!validateKakaoState(parsed.state)) {
      setMsg("보안 검증 실패. 다시 시도해주세요.")
      setTimeout(onError, 1500)
      return
    }

    fetch(`${API_BASE}/auth/kakao/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: 'include',
      body: JSON.stringify({
        code: parsed.code,
        state: parsed.state,
        redirectUri: `${window.location.origin}/kakao/callback`,
      }),
    })
      .then(res => {
        if (!res.ok) return res.json().then(d => Promise.reject(d.detail || "로그인 실패"))
        return res.json()
      })
      .then(user => {
        if (user.requiresProfileCompletion) {
          onProfileRequired(user)
        } else if (user.requiresVerification) {
          onVerificationRequired(user)
        } else {
          onSuccess(user)
        }
      })
      .catch(err => {
        setMsg(typeof err === "string" ? err : "카카오 로그인에 실패했습니다.")
        setTimeout(onError, 2000)
      })
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center">
        <div className="w-10 h-10 border-2 border-[#FEE500] border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-300 text-sm">{msg}</p>
      </div>
    </div>
  )
}
