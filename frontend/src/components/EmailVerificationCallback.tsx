import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { API_BASE } from "../lib/axiosClient"

interface VerifiedUser {
  id: number; name: string; email: string; membership: string;
  accessToken: string; admin?: boolean;
}

interface Props {
  onSuccess: (user: VerifiedUser) => void
  onError: () => void
}

export default function EmailVerificationCallback({ onSuccess, onError }: Props) {
  const [searchParams] = useSearchParams()
  const [msg, setMsg] = useState("이메일 인증 처리 중...")
  const [isError, setIsError] = useState(false)
  const called = useRef(false)

  useEffect(() => {
    if (called.current) return
    called.current = true

    const token = searchParams.get("token")
    if (!token) {
      setMsg("유효하지 않은 인증 링크입니다.")
      setIsError(true)
      return
    }

    fetch(`${API_BASE}/auth/verify?token=${encodeURIComponent(token)}`, { credentials: 'include' })
      .then(res => {
        if (!res.ok) return res.json().then(d => Promise.reject(d.detail || d.error || "인증에 실패했습니다."))
        return res.json()
      })
      .then(data => {
        // 2026-05-10: Spring Boot Jackson SNAKE_CASE 적용 후 access_token. 양쪽 fallback.
        const token = data.accessToken ?? data.access_token
        if (data.verified && token) {
          // 이전 탭("이메일 확인" 화면)이 열려 있을 때 storage 이벤트로 알림
          localStorage.setItem('landup_verified', JSON.stringify({ ...data.user, accessToken: token }))
          setTimeout(() => localStorage.removeItem('landup_verified'), 10000)

          setMsg("이메일 인증이 완료되었습니다! 잠시 후 이동합니다...")
          setTimeout(() => onSuccess({ ...data.user, accessToken: token }), 1200)
        } else {
          setMsg("인증에 실패했습니다.")
          setIsError(true)
        }
      })
      .catch(err => {
        setMsg(typeof err === "string" ? err : "인증에 실패했습니다.")
        setIsError(true)
      })
  }, [])

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="text-center">
        {!isError && (
          <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        )}
        {isError && (
          <div className="w-12 h-12 rounded-full bg-red-900/30 border border-red-800 flex items-center justify-center mx-auto mb-4">
            <svg className="w-5 h-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
        )}
        <p className="text-slate-300 text-sm">{msg}</p>
        {isError && (
          <button
            onClick={onError}
            className="mt-4 text-indigo-400 text-sm hover:text-indigo-300 transition"
          >
            로그인 페이지로 이동
          </button>
        )}
      </div>
    </div>
  )
}
