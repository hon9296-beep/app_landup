const KAKAO_REST_API_KEY = import.meta.env.VITE_KAKAO_REST_API_KEY as string

const REDIRECT_URI = `${window.location.origin}/kakao/callback`

/** Kakao 로그인 URL 생성 (state는 CSRF 방지용 랜덤값) */
export function kakaoLoginUrl(): string | null {
  if (!KAKAO_REST_API_KEY) {
    alert("Kakao 로그인 준비 중 — REST API 키 미등록")
    return null
  }
  const state = crypto.randomUUID()
  sessionStorage.setItem("kakao_oauth_state", state)
  const params = new URLSearchParams({
    response_type: "code",
    client_id:     KAKAO_REST_API_KEY,
    redirect_uri:  REDIRECT_URI,
    state,
    prompt:        "login",  // 항상 카카오 로그인 입력 화면 강제 표시
  })
  return `https://kauth.kakao.com/oauth/authorize?${params.toString()}`
}

/** 콜백 URL에서 code, state 파싱 */
export function parseKakaoCallback(): { code: string; state: string } | null {
  const params = new URLSearchParams(window.location.search)
  const code   = params.get("code")
  const state  = params.get("state")
  if (!code || !state) return null
  return { code, state }
}

/** 저장된 state와 콜백 state 검증 */
export function validateKakaoState(state: string): boolean {
  const saved = sessionStorage.getItem("kakao_oauth_state")
  sessionStorage.removeItem("kakao_oauth_state")
  return saved === state
}
