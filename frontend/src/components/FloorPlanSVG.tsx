/**
 * 도면 SVG 뷰어 — Shin 방식
 * 감지된 polygon + 설비를 SVG로 렌더링. 파일 형식 무관.
 */

interface DetectResult {
  floor_plan?: {
    floor_polygon_px?: number[][]
    entrance?: { x_px: number; y_px: number }
    entrances?: { x_px: number; y_px: number; type: string; is_main: boolean }[]
    sprinklers?: { x_px: number; y_px: number }[]
    fire_hydrant?: { x_px: number; y_px: number }[]
    electrical_panel?: { x_px: number; y_px: number }[]
    scale_mm_per_px?: number
  }
}

interface Marking { x: number; y: number; type: string }

interface Props {
  detect: DetectResult
  markings?: Marking[]
  onSvgClick?: (xRatio: number, yRatio: number) => void
  isMarkingMode?: boolean
  markerColor?: string
}

export default function FloorPlanSVG({ detect, markings = [], onSvgClick, isMarkingMode, markerColor: _markerColor }: Props) {
  const fp = detect.floor_plan
  if (!fp?.floor_polygon_px?.length) {
    return <div style={{ color: '#64748b', textAlign: 'center', padding: '40px' }}>감지된 도면 데이터가 없습니다</div>
  }

  const polygon = fp.floor_polygon_px
  const xs = polygon.map(p => p[0])
  const ys = polygon.map(p => p[1])
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const w = maxX - minX, h = maxY - minY
  const pad = Math.max(w, h) * 0.08

  const vb = `${minX - pad} ${minY - pad} ${w + pad * 2} ${h + pad * 2}`
  const polyPts = polygon.map(p => `${p[0]},${p[1]}`).join(' ')

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!onSvgClick || !isMarkingMode) return
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const xRatio = (e.clientX - rect.left) / rect.width
    const yRatio = (e.clientY - rect.top) / rect.height
    // SVG 좌표로 변환
    const svgX = (minX - pad) + (w + pad * 2) * xRatio
    const svgY = (minY - pad) + (h + pad * 2) * yRatio
    onSvgClick(svgX, svgY)
  }

  const r = Math.max(w, h) * 0.015 // 마커 반지름
  const sw = Math.max(w, h) * 0.004 // 선 두께

  return (
    <svg viewBox={vb} style={{ width: '100%', height: '100%', cursor: isMarkingMode ? 'crosshair' : 'default' }}
      onClick={handleClick}>
      {/* 배경 */}
      <rect x={minX - pad} y={minY - pad} width={w + pad * 2} height={h + pad * 2} fill="#0f172a" />

      {/* 바닥 폴리곤 */}
      <polygon points={polyPts} fill="#1e293b" stroke="#64748b" strokeWidth={sw * 1.5} />

      {/* 입구 */}
      {fp.entrance && (
        <circle cx={fp.entrance.x_px} cy={fp.entrance.y_px} r={r * 1.5}
          fill="#22c55e" fillOpacity={0.3} stroke="#22c55e" strokeWidth={sw} />
      )}
      {fp.entrances?.map((e, i) => (
        <g key={`ent-${i}`}>
          <circle cx={e.x_px} cy={e.y_px} r={r * 1.3}
            fill={e.is_main ? '#22c55e' : '#f59e0b'} fillOpacity={0.3}
            stroke={e.is_main ? '#22c55e' : '#f59e0b'} strokeWidth={sw} />
          <text x={e.x_px} y={e.y_px + r * 2.5} textAnchor="middle"
            fill={e.is_main ? '#22c55e' : '#f59e0b'} fontSize={r * 1.8}>
            {e.is_main ? '입구' : e.type === 'EMERGENCY_EXIT' ? '비상구' : '문'}
          </text>
        </g>
      ))}

      {/* 스프링클러 — 파란 원 */}
      {fp.sprinklers?.map((s, i) => (
        <g key={`sp-${i}`}>
          <circle cx={s.x_px} cy={s.y_px} r={r} fill="none" stroke="#3b82f6" strokeWidth={sw} />
          <circle cx={s.x_px} cy={s.y_px} r={r * 0.3} fill="#3b82f6" />
        </g>
      ))}

      {/* 소화전 — 주황 사각형 */}
      {fp.fire_hydrant?.map((f, i) => (
        <g key={`fh-${i}`}>
          <rect x={f.x_px - r} y={f.y_px - r} width={r * 2} height={r * 2}
            fill="none" stroke="#f97316" strokeWidth={sw} rx={r * 0.2} />
          <text x={f.x_px} y={f.y_px + r * 0.4} textAnchor="middle"
            fill="#f97316" fontSize={r * 1.2} fontWeight="bold">H</text>
        </g>
      ))}

      {/* 분전반 — 보라 사각형 */}
      {fp.electrical_panel?.map((e, i) => (
        <rect key={`ep-${i}`} x={e.x_px - r} y={e.y_px - r} width={r * 2} height={r * 2}
          fill="#a855f7" fillOpacity={0.3} stroke="#a855f7" strokeWidth={sw} rx={r * 0.2} />
      ))}

      {/* 사용자 마킹 */}
      {markings.map((m, i) => {
        const colors: Record<string, string> = {
          sprinkler: '#3b82f6', fire_hydrant: '#f97316',
          electrical_panel: '#a855f7', entrance: '#22c55e', pillar: '#6366f1',
        }
        const c = colors[m.type] || '#fff'
        return (
          <circle key={`mk-${i}`} cx={m.x} cy={m.y} r={r * 1.2}
            fill={c} fillOpacity={0.4} stroke={c} strokeWidth={sw * 1.5} />
        )
      })}
    </svg>
  )
}
