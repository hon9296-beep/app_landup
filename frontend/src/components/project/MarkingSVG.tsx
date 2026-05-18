/**
 * MarkingSVG — 도면 위에 마킹(입구/스프링클러/소화전/분전반/스케일앵커) 표시
 * 기존 AppShellPage에서 이관
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import type { AutoDetected } from '../../types/floor';
import type { MarkMode, Pt2, EntranceMark } from '../../context/ProjectContext';

interface Props {
  polygon: number[][];
  markMode: MarkMode;
  entrance: EntranceMark | null;
  sprinklers: Pt2[];
  fireHydrants: Pt2[];
  electricalPanels: Pt2[];
  onSvgClick: (x: number, y: number) => void;
  anchorPoints?: { x: number; y: number }[];
  imageBase64?: string;
  visionTransform?: AutoDetected['vision_transform'];
  onPolygonChange?: (polygon: number[][]) => void;
}

export default function MarkingSVG({
  polygon, markMode, entrance, sprinklers, fireHydrants, electricalPanels,
  onSvgClick, anchorPoints = [], imageBase64, visionTransform, onPolygonChange,
}: Props) {
  const [draggingIdx, setDraggingIdx] = useState<number | null>(null);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
  // const [snapHoverIdx, setSnapHoverIdx] = useState<number | null>(null);
  const [dragPolygon, setDragPolygon] = useState<number[][] | null>(null);
  const draggingRef = useRef<number | null>(null);
  const polygonRef = useRef<number[][]>(polygon);
  useEffect(() => { polygonRef.current = polygon; }, [polygon]);

  const stableViewBox = useMemo(() => {
    if (!polygon || polygon.length < 3) return null;
    const xs0 = polygon.map(p => p[0]);
    const ys0 = polygon.map(p => p[1]);
    const mnX = Math.min(...xs0), mxX = Math.max(...xs0);
    const mnY = Math.min(...ys0), mxY = Math.max(...ys0);
    const p = (mxX - mnX) * 0.05 || 50;

    if (imageBase64 && visionTransform) {
      const vt = visionTransform;
      const TARGET_W = 1200, TARGET_H = 900, PAD_PT = 60;
      if (vt.type === 'vector_clip' && vt.range_x && vt.range_y) {
        const rx = vt.range_x as number, ry = vt.range_y as number;
        return {
          x: -PAD_PT / rx * TARGET_W,
          y: -PAD_PT / ry * TARGET_H,
          w: (rx + 2 * PAD_PT) / rx * TARGET_W,
          h: (ry + 2 * PAD_PT) / ry * TARGET_H,
        };
      } else if (vt.type === 'image' && vt.range_x && vt.range_y) {
        return { x: 0, y: 0, w: vt.range_x as number, h: vt.range_y as number };
      }
    }
    return { x: mnX - p, y: mnY - p, w: (mxX - mnX) + p * 2, h: (mxY - mnY) + p * 2 };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!polygon || polygon.length < 3)
    return <div className="text-text-muted text-xs text-center p-8">도면 데이터 없음</div>;

  const xs = polygon.map(p => p[0]);
  const ys = polygon.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const pad = (maxX - minX) * 0.05 || 50;

  let imgRect: { x: number; y: number; w: number; h: number } | null = null;
  if (imageBase64 && visionTransform) {
    const vt = visionTransform;
    const TARGET_W = 1200, TARGET_H = 900, PAD_PT = 60;
    if (vt.type === 'vector_clip' && vt.range_x && vt.range_y) {
      imgRect = {
        x: -PAD_PT / (vt.range_x as number) * TARGET_W,
        y: -PAD_PT / (vt.range_y as number) * TARGET_H,
        w: ((vt.range_x as number) + 2 * PAD_PT) / (vt.range_x as number) * TARGET_W,
        h: ((vt.range_y as number) + 2 * PAD_PT) / (vt.range_y as number) * TARGET_H,
      };
    } else if (vt.type === 'image' && vt.range_x && vt.range_y) {
      imgRect = { x: 0, y: 0, w: vt.range_x as number, h: vt.range_y as number };
    }
  }

  const vb = stableViewBox ?? { x: minX - pad, y: minY - pad, w: (maxX - minX) + pad * 2, h: (maxY - minY) + pad * 2 };
  const vx = vb.x, vy = vb.y, vw = vb.w, vh = vb.h;
  const fontSize = vw * 0.025;

  const displayPolygon = dragPolygon ?? polygon;
  const polyPts = displayPolygon.map(p => `${p[0]},${p[1]}`).join(' ');

  const toSvgPt = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svg.getScreenCTM()!.inverse());
  };

  // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가
  // const SNAP_THRESHOLD = 40;

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svgPt = toSvgPt(e);
    if (draggingRef.current !== null && onPolygonChange) {
      const newPoly = polygonRef.current.map((p, i) =>
        i === draggingRef.current ? [Math.round(svgPt.x), Math.round(svgPt.y)] : p
      );
      setDragPolygon(newPoly);
      return;
    }
    // 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가 (꼭짓점 hover 시 노란 링 표시)
    // if (markMode === 'scale_anchor') {
    //   let nearIdx: number | null = null;
    //   let minDist = Infinity;
    //   polygon.forEach(([px, py], i) => {
    //     const d = Math.sqrt((svgPt.x - px) ** 2 + (svgPt.y - py) ** 2);
    //     if (d < SNAP_THRESHOLD && d < minDist) { minDist = d; nearIdx = i; }
    //   });
    //   setSnapHoverIdx(nearIdx);
    // }
  };

  const handleMouseDown = (idx: number, e: React.MouseEvent) => {
    if (markMode) return;
    e.stopPropagation();
    draggingRef.current = idx;
    setDraggingIdx(idx);
  };

  const handleMouseUp = () => {
    if (draggingRef.current !== null) {
      draggingRef.current = null;
      setDraggingIdx(null);
      if (onPolygonChange && dragPolygon) onPolygonChange(dragPolygon);
      setDragPolygon(null);
    }
  };

  const handleClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (draggingRef.current !== null) return;
    if (!markMode) return;
    const svgPt = toSvgPt(e);
    onSvgClick(Math.round(svgPt.x), Math.round(svgPt.y));
  };

  return (
    <svg viewBox={`${vx} ${vy} ${vw} ${vh}`} style={{ aspectRatio: '4/3' }}
      className={`w-full h-full rounded-xl border border-border bg-[#070d1a] select-none ${
        draggingIdx !== null ? 'cursor-grabbing' : markMode ? 'cursor-crosshair' : 'cursor-default'
      }`}
      onClick={handleClick}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      {imageBase64 && imgRect && (
        <image href={`data:image/png;base64,${imageBase64}`}
          x={imgRect.x} y={imgRect.y} width={imgRect.w} height={imgRect.h} opacity={0.45} />
      )}
      <polygon points={polyPts} fill="rgba(30,41,59,0.5)" stroke="#3b82f6" strokeWidth={vw * 0.004} />
      {entrance && (
        <g>
          {entrance.points && entrance.points.length > 1 ? (
            <>
              <polyline points={entrance.points.map(p => `${p.x_px},${p.y_px}`).join(' ')}
                fill="none" stroke="#22c55e" strokeWidth={vw * 0.007} strokeLinecap="round" opacity={0.9} />
              {entrance.points.map((p, i) => <circle key={i} cx={p.x_px} cy={p.y_px} r={vw * 0.009} fill="#22c55e" />)}
              <text x={entrance.points.reduce((s, p) => s + p.x_px, 0) / entrance.points.length}
                y={entrance.points.reduce((s, p) => s + p.y_px, 0) / entrance.points.length - fontSize}
                textAnchor="middle" fontSize={fontSize} fill="#4ade80">입구</text>
            </>
          ) : (
            <>
              <circle cx={entrance.x_px} cy={entrance.y_px} r={vw * 0.02} fill="#22c55e" opacity={0.9} />
              <text x={entrance.x_px} y={entrance.y_px + fontSize * 0.4} textAnchor="middle" fontSize={fontSize} fontWeight="bold" fill="white">▼</text>
              <text x={entrance.x_px} y={entrance.y_px - fontSize * 1.5} textAnchor="middle" fontSize={fontSize} fill="#4ade80">입구</text>
            </>
          )}
        </g>
      )}
      {sprinklers.map((s, i) => (
        <g key={i}>
          <circle cx={s.x_px} cy={s.y_px} r={vw * 0.016} fill="none" stroke="#3b82f6" strokeWidth={vw * 0.003} />
          <circle cx={s.x_px} cy={s.y_px} r={vw * 0.003} fill="#3b82f6" />
          <text x={s.x_px} y={s.y_px - vw * 0.022} textAnchor="middle" fontSize={fontSize * 0.9} fill="#60a5fa">SP</text>
        </g>
      ))}
      {fireHydrants.map((s, i) => (
        <g key={i}>
          <rect x={s.x_px - vw * 0.016} y={s.y_px - vw * 0.016} width={vw * 0.032} height={vw * 0.032} fill="none" stroke="#f97316" strokeWidth={vw * 0.003} />
          <text x={s.x_px} y={s.y_px + fontSize * 0.4} textAnchor="middle" fontSize={fontSize * 0.9} fill="#fb923c">FH</text>
        </g>
      ))}
      {electricalPanels.map((s, i) => (
        <g key={i}>
          <rect x={s.x_px - vw * 0.014} y={s.y_px - vw * 0.014} width={vw * 0.028} height={vw * 0.028} fill="#a855f7" opacity={0.5} />
          <rect x={s.x_px - vw * 0.014} y={s.y_px - vw * 0.014} width={vw * 0.028} height={vw * 0.028} fill="none" stroke="#a855f7" strokeWidth={vw * 0.003} />
          <text x={s.x_px} y={s.y_px + fontSize * 0.4} textAnchor="middle" fontSize={fontSize * 0.9} fill="white">EP</text>
        </g>
      ))}
      {/* 스케일 수동 앵커 — 추후 기능 필요 시 다시 추가 (앵커 점 및 snap hover 링 렌더링) */}
      {/* {anchorPoints.length === 2 && (
        <line x1={anchorPoints[0].x} y1={anchorPoints[0].y} x2={anchorPoints[1].x} y2={anchorPoints[1].y}
          stroke="#eab308" strokeWidth={vw * 0.002} strokeDasharray={`${vw * 0.006} ${vw * 0.003}`} />
      )}
      {anchorPoints.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r={vw * 0.012} fill="#eab308" stroke="#fff" strokeWidth={vw * 0.002} />
          <text x={p.x} y={p.y + fontSize * 0.4} textAnchor="middle" fontSize={fontSize} fontWeight="bold" fill="#fff">{i + 1}</text>
        </g>
      ))}
      {markMode === 'scale_anchor' && snapHoverIdx !== null && (
        <circle cx={polygon[snapHoverIdx][0]} cy={polygon[snapHoverIdx][1]}
          r={vw * 0.018} fill="none" stroke="#eab308" strokeWidth={vw * 0.003} opacity={0.8} />
      )} */}
      {!markMode && onPolygonChange && displayPolygon.map(([px, py], i) => (
        <circle key={i} cx={px} cy={py}
          r={hoveredIdx === i ? vw * 0.014 : vw * 0.009}
          fill={draggingIdx === i ? '#f59e0b' : hoveredIdx === i ? '#eab308' : '#3b82f6'}
          stroke="#fff" strokeWidth={vw * 0.002} style={{ cursor: 'grab' }}
          onMouseEnter={() => setHoveredIdx(i)}
          onMouseLeave={() => setHoveredIdx(null)}
          onMouseDown={e => handleMouseDown(i, e)} />
      ))}
      {markMode && !entrance && sprinklers.length === 0 && anchorPoints.length === 0 && (
        <text x={minX + (maxX - minX) / 2} y={minY + (maxY - minY) / 2} textAnchor="middle" fontSize={fontSize * 1.5} fill="#334155">클릭하여 위치를 지정하세요</text>
      )}
    </svg>
  );
}
