/**
 * 수동 마킹 SVG 아이콘 — HiMedia 베이스
 * 5종: 스프링클러, 소화전, 분전반, 출입구, 기둥
 */

export type MarkerType = 'sprinkler' | 'fire_hydrant' | 'electrical_panel' | 'entrance' | 'pillar'

export const MARKER_CONFIG: Record<MarkerType, { label: string; color: string }> = {
  sprinkler:        { label: '스프링클러', color: '#ef4444' },
  fire_hydrant:     { label: '소화전',     color: '#f97316' },
  electrical_panel: { label: '분전반',     color: '#eab308' },
  entrance:         { label: '출입구',     color: '#22c55e' },
  pillar:           { label: '기둥',       color: '#6366f1' },
}

export function MarkerSVG({ type, size = 24 }: { type: MarkerType; size?: number }) {
  const cfg = MARKER_CONFIG[type]
  const c = cfg.color
  const _r = size / 2

  switch (type) {
    case 'sprinkler':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="8" fill="none" stroke={c} strokeWidth="2" />
          <line x1="12" y1="2" x2="12" y2="6" stroke={c} strokeWidth="2" />
          <line x1="12" y1="18" x2="12" y2="22" stroke={c} strokeWidth="2" />
          <line x1="2" y1="12" x2="6" y2="12" stroke={c} strokeWidth="2" />
          <line x1="18" y1="12" x2="22" y2="12" stroke={c} strokeWidth="2" />
        </svg>
      )
    case 'fire_hydrant':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" fill="none" stroke={c} strokeWidth="2" />
          <text x="12" y="16" textAnchor="middle" fill={c} fontSize="12" fontWeight="bold">H</text>
        </svg>
      )
    case 'electrical_panel':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24">
          <rect x="3" y="3" width="18" height="18" rx="2" fill="none" stroke={c} strokeWidth="2" />
          <path d="M13 3L10 13h4l-3 8" stroke={c} strokeWidth="2" fill="none" />
        </svg>
      )
    case 'entrance':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24">
          <line x1="4" y1="4" x2="4" y2="20" stroke={c} strokeWidth="2" />
          <path d="M4 4 A16 16 0 0 1 20 4" fill="none" stroke={c} strokeWidth="2" />
        </svg>
      )
    case 'pillar':
      return (
        <svg width={size} height={size} viewBox="0 0 24 24">
          <rect x="6" y="6" width="12" height="12" fill={c} rx="1" />
        </svg>
      )
  }
}
