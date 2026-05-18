const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string

const REDIRECT_URI = `${window.location.origin}/google/callback`

/** Google 로그인 URL 생성 (state는 CSRF 방지용 랜덤값) */
export function googleLoginUrl(): string | null {
  if (!GOOGLE_CLIENT_ID) {
    alert("Google 로그인 준비 중 — Client ID 미등록")
    return null
  }
  const state = crypto.randomUUID()
  sessionStorage.setItem("google_oauth_state", state)
  const params = new URLSearchParams({
    response_type: "code",
    client_id:     GOOGLE_CLIENT_ID,
    redirect_uri:  REDIRECT_URI,
    scope:         "openid email profile",
    state,
    prompt:        "select_account",  // 항상 계정 선택 화면 강제 표시
    access_type:   "offline",
  })
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`
}

/** 콜백 URL에서 code, state 파싱 */
export function parseGoogleCallback(): { code: string; state: string } | null {
  const params = new URLSearchParams(window.location.search)
  const code   = params.get("code")
  const state  = params.get("state")
  if (!code || !state) return null
  return { code, state }
}

/** 저장된 state와 콜백 state 검증 */
export function validateGoogleState(state: string): boolean {
  const saved = sessionStorage.getItem("google_oauth_state")
  sessionStorage.removeItem("google_oauth_state")
  return saved === state
}
