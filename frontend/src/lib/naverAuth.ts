const NAVER_CLIENT_ID = import.meta.env.VITE_NAVER_CLIENT_ID as string
const REDIRECT_URI    = `${window.location.origin}/naver/callback`

/** 네이버 로그인 URL 생성 (state는 CSRF 방지용 랜덤값) */
export function naverLoginUrl(): string {
  const state = crypto.randomUUID()
  sessionStorage.setItem("naver_oauth_state", state)
  const params = new URLSearchParams({
    response_type: "code",
    client_id:     NAVER_CLIENT_ID,
    redirect_uri:  REDIRECT_URI,
    state,
  })
  return `https://nid.naver.com/oauth2.0/authorize?${params.toString()}`
}

/** 콜백 URL에서 code, state 파싱 */
export function parseNaverCallback(): { code: string; state: string } | null {
  const params = new URLSearchParams(window.location.search)
  const code   = params.get("code")
  const state  = params.get("state")
  if (!code || !state) return null
  return { code, state }
}

/** 저장된 state와 콜백 state 검증 */
export function validateNaverState(state: string): boolean {
  const saved = sessionStorage.getItem("naver_oauth_state")
  sessionStorage.removeItem("naver_oauth_state")
  return saved === state
}
