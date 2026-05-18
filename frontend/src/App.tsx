import AppRoutes from './AppRoutes'
import TokenUsageBadge from './components/TokenUsageBadge'

export default function App() {
  return (
    <>
      <AppRoutes />
      {/* 전역 좌하단 토큰 비용 배지 — dev 용. 라우트 무관 viewport 고정. */}
      <TokenUsageBadge />
    </>
  )
}
