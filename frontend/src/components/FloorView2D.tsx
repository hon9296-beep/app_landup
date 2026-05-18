/**
 * FloorView2D — BuildUp 디자인 이식 (SVG 기반 2D 평면도 뷰어)
 * PlacedObject[] (position_mm / bbox_mm 포맷) 입력.
 * App.tsx에서 LayoutObject → PlacedObject 변환 후 전달.
 */
import React, { useMemo, useState, useRef, useCallback, useEffect } from 'react';
import type { Wall } from './ThreeViewer';

export interface PlacedObject {
  object_type: string;
  position_mm: [number, number];
  rotation_deg: number;
  bbox_mm: [number, number];
  height_mm: number;
  reference_point: string;
  placed_because: string;
}

export interface DetectedObject {
  equipment_type: string;
  position_mm: [number, number];
  size_mm?: [number, number];
}

interface FloorView2DProps {
  roomPolygon: [number, number][];
  placedObjects: PlacedObject[];
  detectedObjects?: DetectedObject[];
  walls?: Wall[];
  selectedIndices?: number[];
  onObjectClick?: (index: number | null, shiftKey?: boolean) => void;
  onObjectRotate?: (index: number, deltaDeg: number) => void;
}

// utils.py OBJECT_STANDARDS + nodes_small/reference.py 정식 기준 (진규 쪽과 통합)
const OBJECT_COLORS: Record<string, string> = {
  counter:          '#fde68a',
  display_table:    '#bbf7d0',
  character_bbox:   '#c4b5fd',
  photo_wall:       '#fed7aa',
  photo_island:     '#fbbf24',
  shelf_wall:       '#bfdbfe',
  shelf_3tier:      '#dbeafe',
  banner_stand:     '#fef3c7',
  partition_wall_I: '#f1f5f9',
  partition_wall_L: '#cbd5e1',
  signage_stand:    '#fecaca',
  kiosk:            '#ddd6fe',
};

const OBJECT_NAMES: Record<string, string> = {
  counter:          '계산대',
  display_table:    '진열대',
  character_bbox:   '캐릭터 조형물',
  photo_wall:       '포토월',
  photo_island:     '포토 아일랜드',
  shelf_wall:       '벽면 선반',
  shelf_3tier:      '3단 선반',
  banner_stand:     '배너',
  partition_wall_I: '가벽(일자형)',
  partition_wall_L: '가벽(ㄱ자형)',
  signage_stand:    '안내판',
  kiosk:            '키오스크',
};

const PADDING = 40;
const CANVAS_SIZE = 700; // 긴 축 기준 해상도

const FloorView2D: React.FC<FloorView2DProps> = ({
  roomPolygon, placedObjects, detectedObjects = [], walls = [],
  selectedIndices = [], onObjectClick, onObjectRotate,
}) => {
  const { scale, minX, minY, toSVG, contentW, contentH } = useMemo(() => {
    if (roomPolygon.length === 0) {
      return { scale: 1, minX: 0, minY: 0, contentW: CANVAS_SIZE, contentH: CANVAS_SIZE,
        toSVG: (x: number, y: number) => [x, y] as [number, number] };
    }
    const xs = roomPolygon.map(p => p[0]);
    const ys = roomPolygon.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const roomW = maxX - minX, roomH = maxY - minY;
    // 도면 비율 유지, 긴 축을 CANVAS_SIZE 기준으로 스케일
    const scale = (CANVAS_SIZE - PADDING * 2) / Math.max(roomW, roomH);
    const contentW = roomW * scale + PADDING * 2;
    const contentH = roomH * scale + PADDING * 2;
    const toSVG = (x: number, y: number): [number, number] => [
      (x - minX) * scale + PADDING,
      (y - minY) * scale + PADDING,
    ];
    return { scale, minX, minY, contentW, contentH, toSVG };
  }, [roomPolygon]);

  const roomPoints = roomPolygon.map(([x, y]) => toSVG(x, y).join(',')).join(' ');

  // ── 줌/패닝 ──
  const [zoom, setZoom] = useState(0.85);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const hasDragged = useRef(false);
  const panStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setZoom(z => Math.max(0.5, Math.min(5, z - e.deltaY * 0.001)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0 || e.button === 1) {
      isDragging.current = true;
      hasDragged.current = false;
      panStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    }
  }, [pan]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - panStart.current.x;
    const dy = e.clientY - panStart.current.y;
    if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
      hasDragged.current = true;
    }
    if (hasDragged.current) {
      setPan({ x: panStart.current.panX + dx, y: panStart.current.panY + dy });
    }
  }, []);

  const handleMouseUp = useCallback(() => { isDragging.current = false; }, []);

  const vbW = contentW / zoom;
  const vbH = contentH / zoom;
  const vbX = (contentW - vbW) / 2 - pan.x / zoom;
  const vbY = (contentH - vbH) / 2 - pan.y / zoom;

  return (
    <div ref={containerRef} className="w-full h-full flex items-center justify-center bg-[#0a0f1d] relative overflow-hidden">
      <svg
        viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`}
        width="100%" height="100%"
        style={{ maxHeight: '100%', userSelect: 'none', cursor: 'grab' }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={() => { if (hasDragged.current) { hasDragged.current = false; return; } onObjectClick?.(null); }}
      >
        {/* 배경 격자 */}
        <defs>
          <pattern id="grid2d" width={scale * 500} height={scale * 500} patternUnits="userSpaceOnUse"
            x={PADDING - minX * scale} y={PADDING - minY * scale}>
            <path d={`M ${scale * 500} 0 L 0 0 0 ${scale * 500}`} fill="none" stroke="#1e293b" strokeWidth="0.5" />
          </pattern>
        </defs>
        <rect width={contentW} height={contentH} fill="url(#grid2d)" />

        {/* 방 외곽 */}
        <polygon points={roomPoints} fill="#1e3a5f" fillOpacity={0.5} stroke="#6366f1" strokeWidth="2" />

        {/* 감지된 설비 */}
        {detectedObjects.map((obj, i) => {
          if (!obj.position_mm) return null;
          const [cx, cy] = toSVG(obj.position_mm[0], obj.position_mm[1]);
          const type = obj.equipment_type;
          if (type === 'sprinkler') {
            return (
              <g key={`eq-${i}`}>
                <circle cx={cx} cy={cy} r={10} fill="#ef4444" stroke="#ff0000" strokeWidth="2" />
                <circle cx={cx} cy={cy} r={4} fill="#ffffff" />
              </g>
            );
          }
          if (type === 'exit' || type === 'emergency_exit') {
            const w = (obj.size_mm ? obj.size_mm[0] : 350) * scale;
            const d = (obj.size_mm ? obj.size_mm[1] : 350) * scale;
            return (
              <g key={`eq-${i}`}>
                <rect x={cx - w / 2} y={cy - d / 2} width={w} height={d}
                  fill="#22c55e" fillOpacity={0.4} stroke="#4ade80" strokeWidth="2" rx="2" />
                <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle"
                  fontSize="9" fill="#4ade80" fontWeight="bold">EXIT</text>
              </g>
            );
          }
          return <circle key={`eq-${i}`} cx={cx} cy={cy} r={8} fill="#64748b" stroke="#94a3b8" strokeWidth="1.5" />;
        })}

        {/* AI 배치 오브젝트 */}
        {placedObjects.map((obj, i) => {
          const [cx, cy] = toSVG(obj.position_mm[0], obj.position_mm[1]);
          const w = obj.bbox_mm[0] * scale;
          const d = obj.bbox_mm[1] * scale;
          const isSelected = selectedIndices.includes(i);
          const color = OBJECT_COLORS[obj.object_type] ?? '#ec4899';
          const name = OBJECT_NAMES[obj.object_type] ?? obj.object_type;
          return (
            <g
              key={`obj-${i}`}
              transform={`translate(${cx}, ${cy}) rotate(${obj.rotation_deg})`}
              onClick={(e) => {
                e.stopPropagation();
                onObjectClick?.(selectedIndices.includes(i) && !e.shiftKey ? null : i, e.shiftKey);
              }}
              onContextMenu={(e) => {
                e.preventDefault(); e.stopPropagation();
                if (selectedIndices.includes(i)) onObjectRotate?.(i, 45);
              }}
              style={{ cursor: 'pointer' }}
            >
              <rect
                x={-w / 2} y={-d / 2} width={w} height={d}
                fill={color} fillOpacity={isSelected ? 0.95 : 0.7}
                stroke={isSelected ? '#ffd700' : '#ffffff'}
                strokeWidth={isSelected ? 2.5 : 1} rx="3"
              />
              {isSelected && (
                <rect x={-w / 2 - 3} y={-d / 2 - 3} width={w + 6} height={d + 6}
                  fill="none" stroke="#ffd700" strokeWidth="1.5" strokeDasharray="4 2" rx="4" />
              )}
              <text x={0} y={0} textAnchor="middle" dominantBaseline="middle"
                fontSize={Math.max(8, Math.min(w, d) * 0.18)} fill="#ffffff" fontWeight="bold"
                style={{ pointerEvents: 'none' }}>{name}</text>
              <text x={w / 2 - 4} y={-d / 2 + 8} textAnchor="end" fontSize="7"
                fill="rgba(255,255,255,0.6)" style={{ pointerEvents: 'none' }}>{i + 1}</text>
            </g>
          );
        })}

        {/* 가벽 */}
        {walls.map((wall) => {
          const [cx, cy] = toSVG(wall.x, wall.z);
          const w = wall.length * scale;
          const d = wall.thickness * scale;
          return (
            <g key={wall.id} transform={`translate(${cx}, ${cy}) rotate(${wall.rotation})`}>
              <rect x={-w / 2} y={-d / 2} width={w} height={Math.max(d, 3)}
                fill="#94a3b8" fillOpacity={0.85} stroke="#e2e8f0" strokeWidth="1.5" rx="1" />
            </g>
          );
        })}

        {/* 스케일 바 (500mm) */}
        <g transform={`translate(${PADDING}, ${contentH - 20})`}>
          <line x1="0" y1="0" x2={scale * 500} y2="0" stroke="#64748b" strokeWidth="2" />
          <line x1="0" y1="-4" x2="0" y2="4" stroke="#64748b" strokeWidth="1.5" />
          <line x1={scale * 500} y1="-4" x2={scale * 500} y2="4" stroke="#64748b" strokeWidth="1.5" />
          <text x={scale * 250} y="-6" textAnchor="middle" fontSize="9" fill="#64748b">500mm</text>
        </g>
      </svg>

      {/* 범례 (HTML 오버레이 — 줌 영향 안 받음) */}
      <div className="absolute top-3 right-24 bg-black/60 rounded-lg px-2.5 py-1.5 text-[9px] space-y-1 select-none pointer-events-none">
        <div className="flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-red-500 shrink-0" />
          <span className="text-slate-300">스프링클러</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-3 h-2.5 rounded-sm bg-green-500/70 shrink-0" />
          <span className="text-slate-300">비상구</span>
        </div>
      </div>
    </div>
  );
};

export default FloorView2D;
