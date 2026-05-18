/**
 * SpaceConfirmSVG — 공간 분석 결과 시각화 (zone, dead_zone, reference_points, main_artery)
 */
import type { SpaceData } from '../../types/floor';

interface Props {
  spaceData: SpaceData;
}

export default function SpaceConfirmSVG({ spaceData }: Props) {
  const W = 1100, H = 1050;
  const poly = spaceData.floor?.polygon_mm ?? [];
  if (poly.length < 3) return <div className="text-text-muted text-xs text-center p-8">평면도 데이터 없음</div>;
  const xs = poly.map((p: number[]) => p[0]);
  const ys = poly.map((p: number[]) => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = 90;
  const scale = Math.min((W - pad * 2) / (maxX - minX), (H - pad * 2) / (maxY - minY));
  const offsetX = (W - (maxX - minX) * scale) / 2;
  const offsetY = (H - (maxY - minY) * scale) / 2;
  const tx = (v: number) => (v - minX) * scale + offsetX;
  const ty = (v: number) => (v - minY) * scale + offsetY;
  const polyPts = poly.map((p: number[]) => `${tx(p[0])},${ty(p[1])}`).join(' ');

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ aspectRatio: '4/3' }} className="w-full h-full rounded-xl border border-border bg-[#070d1a]">
      <defs>
        <clipPath id="floor-clip">
          <polygon points={polyPts} />
        </clipPath>
      </defs>
      <polygon points={polyPts} fill="#1e293b" stroke="#475569" strokeWidth={2} />
      {spaceData.zone_map && Object.entries(spaceData.zone_map).map(([zoneName, zoneData]: [string, any]) => {
        const zPoly = zoneData.polygon_mm;
        if (!zPoly || zPoly.length < 3) return null;
        const colors: Record<string, string> = {
          entrance_zone: 'rgba(34,197,94,0.15)', mid_zone: 'rgba(234,179,8,0.15)', deep_zone: 'rgba(59,130,246,0.15)',
        };
        const strokes: Record<string, string> = {
          entrance_zone: 'rgba(34,197,94,0.4)', mid_zone: 'rgba(234,179,8,0.4)', deep_zone: 'rgba(59,130,246,0.4)',
        };
        const zPts = zPoly.map((p: number[]) => `${tx(p[0])},${ty(p[1])}`).join(' ');
        return (
          <g key={zoneName}>
            <polygon points={zPts} fill={colors[zoneName] || 'rgba(100,100,100,0.1)'}
              stroke={strokes[zoneName] || 'rgba(100,100,100,0.3)'} strokeWidth={1} />
          </g>
        );
      })}
      <g clipPath="url(#floor-clip)">
        {spaceData.dead_zones?.map((dz: any, i: number) => {
          if (dz.polygon_mm && dz.polygon_mm.length >= 3) {
            const dzPts = dz.polygon_mm.map((p: number[]) => `${tx(p[0])},${ty(p[1])}`).join(' ');
            return <polygon key={i} points={dzPts} fill="rgba(239,68,68,0.18)" stroke="rgba(239,68,68,0.55)" strokeWidth={1.5} />;
          }
          const r = Math.max(3, dz.radius_mm * scale);
          const cx = tx(dz.center_mm[0]), cy = ty(dz.center_mm[1]);
          return <rect key={i} x={cx - r} y={cy - r} width={r * 2} height={r * 2}
            fill="rgba(239,68,68,0.18)" stroke="rgba(239,68,68,0.55)" strokeWidth={1.5} />;
        })}
      </g>
      {Object.entries(spaceData.reference_points ?? {}).map(([key, pt]: [string, any]) => (
        <circle key={key} cx={tx(pt.x_mm)} cy={ty(pt.y_mm)} r={3.5} fill="#3b82f6" opacity={0.7} stroke="white" strokeWidth={0.8}>
          <title>{key}</title>
        </circle>
      ))}
      {(spaceData as any).main_artery?.length >= 2 && (
        <polyline
          points={(spaceData as any).main_artery.map((p: number[]) => `${tx(p[0])},${ty(p[1])}`).join(' ')}
          fill="none" stroke="#f59e0b" strokeWidth={2} strokeDasharray="6,3" opacity={0.7} />
      )}
      {spaceData.entrance && (
        <circle cx={tx(spaceData.entrance.x_mm)} cy={ty(spaceData.entrance.y_mm)} r={7} fill="#22c55e" opacity={0.9} />
      )}
    </svg>
  );
}
