import { Suspense, useMemo, useRef, useEffect, useState, Component } from "react"
import type { ReactNode } from "react"
import { Canvas, useThree } from "@react-three/fiber"
import { OrbitControls, Grid, Text, GizmoHelper, GizmoViewport, Line, useGLTF } from "@react-three/drei"
import * as THREE from "three"
import type { SpaceData, LayoutObject } from "../../types/floor"
import ViewerActionButtons from "./ViewerActionButtons"
import { debugLog } from "../../lib/debug"

const MM = 0.001

// ── 객체 ↔ dead_zone collision 검사 helper (4-28 신설) ────────────────────
// 1. dead_zone 에 polygon_mm 있으면 객체 4 corner 가 polygon 안에 하나라도 있으면 hit
// 2. polygon 없으면 disk (center_mm + radius_mm) 와 객체 외접원 거리 비교
// 정확도보다 빠름 우선 — 95% 케이스 커버. 회전 적용.

function pointInPolygon(pt: number[], poly: number[][]): boolean {
  const [x, y] = pt
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i]
    const [xj, yj] = poly[j]
    const intersect = ((yi > y) !== (yj > y)) &&
                      (x < ((xj - xi) * (y - yi)) / (yj - yi) + xi)
    if (intersect) inside = !inside
  }
  return inside
}

function objectCorners(obj: { center_x_mm: number; center_y_mm: number; width_mm: number; depth_mm: number; rotation_deg: number }): number[][] {
  const rad = (obj.rotation_deg * Math.PI) / 180
  const cos = Math.cos(rad), sin = Math.sin(rad)
  const hw = obj.width_mm / 2, hd = obj.depth_mm / 2
  const local = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]]
  return local.map(([x, y]) => [
    x * cos - y * sin + obj.center_x_mm,
    x * sin + y * cos + obj.center_y_mm,
  ])
}

function objectHitsDeadZone(
  obj: { id: string; center_x_mm: number; center_y_mm: number; width_mm: number; depth_mm: number; rotation_deg: number },
  dz: { center_mm: number[]; radius_mm: number; polygon_mm?: number[][] } & Record<string, unknown>,
): boolean {
  const corners = objectCorners(obj)
  // polygon 있으면 corner-in-polygon 검사
  const poly = (dz as { polygon_mm?: number[][] }).polygon_mm
  if (poly && poly.length >= 3) {
    return corners.some(c => pointInPolygon(c, poly))
  }
  // polygon 없으면 disk 거리 검사 (객체 외접원 vs dead_zone disk)
  if (Array.isArray(dz.center_mm) && dz.center_mm.length >= 2 && typeof dz.radius_mm === 'number') {
    const dx = obj.center_x_mm - dz.center_mm[0]
    const dy = obj.center_y_mm - dz.center_mm[1]
    const dist = Math.sqrt(dx * dx + dy * dy)
    const objR = Math.sqrt((obj.width_mm / 2) ** 2 + (obj.depth_mm / 2) ** 2)
    return dist < dz.radius_mm + objR
  }
  return false
}

// utils.py OBJECT_STANDARDS + nodes_small/reference.py VMD_BOUNDARIES.std 기준 — 진규 쪽과 통합
const OBJ_CFG: Record<string, { color: string; edgeColor: string; h: number }> = {
  counter:          { color: "#fde68a", edgeColor: "#b45309", h: 0.9 },
  display_table:    { color: "#bbf7d0", edgeColor: "#15803d", h: 0.85 },
  character_bbox:   { color: "#c4b5fd", edgeColor: "#7c3aed", h: 1.8 },
  photo_wall:       { color: "#fed7aa", edgeColor: "#c2410c", h: 2.2 },
  photo_island:     { color: "#fbbf24", edgeColor: "#b45309", h: 2.2 },
  shelf_wall:       { color: "#bfdbfe", edgeColor: "#1d4ed8", h: 1.8 },
  shelf_3tier:      { color: "#dbeafe", edgeColor: "#2563eb", h: 1.2 },
  banner_stand:     { color: "#fef3c7", edgeColor: "#b45309", h: 1.8 },
  partition_wall_I: { color: "#f1f5f9", edgeColor: "#64748b", h: 2.4 },
  partition_wall_L: { color: "#cbd5e1", edgeColor: "#475569", h: 2.4 },
  signage_stand:    { color: "#fecaca", edgeColor: "#dc2626", h: 0.9 },
  kiosk:            { color: "#ddd6fe", edgeColor: "#6d28d9", h: 1.7 },
  gondola_shelf:     { color: "#99f6e4", edgeColor: "#0f766e", h: 1.8 },
  display_rack_tall: { color: "#5eead4", edgeColor: "#0f766e", h: 1.8 },
  pegboard_stand:    { color: "#2dd4bf", edgeColor: "#0f766e", h: 1.8 },
  end_cap_shelf:     { color: "#14b8a6", edgeColor: "#0f766e", h: 1.6 },
  tower_display:     { color: "#0d9488", edgeColor: "#134e4a", h: 2.0 },
  folding_chair:  { color: "#e0f2fe", edgeColor: "#0369a1", h: 0.88 },
  bar_stool:      { color: "#fef3c7", edgeColor: "#92400e", h: 1.05 },
  office_chair:   { color: "#e2e8f0", edgeColor: "#475569", h: 1.20 },
  lounge_chair:   { color: "#fce7f3", edgeColor: "#9d174d", h: 0.90 },
  dining_chair:   { color: "#fef9c3", edgeColor: "#713f12", h: 0.90 },
}
const OBJ_DEFAULT = { color: "#e2e8f0", edgeColor: "#475569", h: 1.0 }

// public/models/ 에 GLB 파일을 놓으면 해당 기물이 폴리곤 모델로 렌더링됨. 파일 없으면 바운딩박스 fallback.
const MODEL_PATHS: Partial<Record<string, string>> = {
  gondola_shelf:     '/models/gondola_shelf.glb',
  display_rack_tall: '/models/display_rack_tall.glb',
  pegboard_stand:    '/models/pegboard_stand.glb',
  end_cap_shelf:     '/models/end_cap_shelf.glb',
  tower_display:     '/models/tower_display.glb',
  folding_chair:     '/models/folding_chair.glb',
  bar_stool:         '/models/bar_stool.glb',
  office_chair:      '/models/office_chair.glb',
  lounge_chair:      '/models/lounge_chair.glb',
  dining_chair:      '/models/dining_chair.glb',
}

class ModelErrorBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { error: boolean }
> {
  state = { error: false }
  static getDerivedStateFromError() { return { error: true } }
  render() { return this.state.error ? this.props.fallback : this.props.children }
}

function GlbModel({ path, w, h, d }: { path: string; w: number; h: number; d: number }) {
  const { scene } = useGLTF(path)
  const cloned = useMemo(() => scene.clone(true), [scene])

  const [groupPos, groupScale] = useMemo<[[number, number, number], [number, number, number]]>(() => {
    const box = new THREE.Box3().setFromObject(cloned)
    const size = new THREE.Vector3()
    box.getSize(size)
    if (size.x < 1e-4 || size.y < 1e-4 || size.z < 1e-4) return [[0, 0, 0], [1, 1, 1]]
    const sx = w / size.x, sy = h / size.y, sz = d / size.z
    const center = new THREE.Vector3()
    box.getCenter(center)
    return [
      [-center.x * sx, -box.min.y * sy, -center.z * sz],
      [sx, sy, sz],
    ]
  }, [cloned, w, h, d])

  return (
    <group position={groupPos} scale={groupScale}>
      <primitive object={cloned} />
    </group>
  )
}


// ── 프로시져럴 진열대 모델 ─────────────────────────────────────────────────────
// GLB 파일 없이도 실물 형태를 표현. 박스 조합으로 각 기물 특징 재현.
function Slab({
  p, s, c, m = 0.5, r = 0.4,
}: { p: [number,number,number]; s: [number,number,number]; c: string; m?: number; r?: number }) {
  return (
    <mesh position={p} receiveShadow castShadow>
      <boxGeometry args={s} />
      <meshStandardMaterial color={c} metalness={m} roughness={r} />
    </mesh>
  )
}

const MC = {
  frame: "#4b5563", base: "#374151", board: "#d1d5db", light: "#f3f4f6",
  wood: "#92400e", woodLight: "#b45309",
  fabric: "#94a3b8", cushion: "#e2e8f0", leather: "#1f2937",
}

function ProceduralShelfModel({ type, w, h, d }: { type: string; w: number; h: number; d: number }) {
  switch (type) {
    case 'gondola_shelf': {
      // 양측 진열대: 좌우 측면 패널 + 바닥 + 5단 선반
      const pw = w * 0.04, bh = h * 0.05, st = h * 0.012, sd = d * 0.88
      return (
        <group>
          <Slab p={[0, bh/2, 0]} s={[w, bh, d]} c={MC.base} m={0.7} r={0.3} />
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*(w/2-pw/2), h/2, 0]} s={[pw, h, d]} c={MC.frame} m={0.7} r={0.3} />
          ))}
          {[0.12, 0.30, 0.48, 0.66, 0.85].map((f, i) => (
            <Slab key={i} p={[0, f*h, 0]} s={[w-pw*2, st, sd]} c={MC.board} m={0.1} r={0.5} />
          ))}
        </group>
      )
    }
    case 'display_rack_tall': {
      // 오픈 프레임 랙: 4개 코너 기둥 + 베이스 + 5단 선반 (창고형 개방 구조)
      const leg = w * 0.025, bh = h * 0.04, st = h * 0.013
      return (
        <group>
          <Slab p={[0, bh/2, 0]} s={[w, bh, d]} c={MC.base} m={0.8} r={0.2} />
          {[-1, 1].flatMap(sx =>
            [-1, 1].map(sz => (
              <Slab key={`${sx}${sz}`} p={[sx*(w/2-leg/2), h/2, sz*(d/2-leg/2)]} s={[leg, h, leg]} c={MC.frame} m={0.8} r={0.2} />
            ))
          )}
          {[0.15, 0.35, 0.55, 0.75, 0.92].map((f, i) => (
            <Slab key={i} p={[0, f*h, 0]} s={[w-leg, st, d-leg]} c={MC.board} m={0.1} r={0.5} />
          ))}
        </group>
      )
    }
    case 'pegboard_stand': {
      // 페그보드: 전/후 받침 발판 + 양쪽 수직 폴 + 대형 수직 패널 + 헤더
      const bh = h * 0.035, fw = d * 0.6, pw = w * 0.025
      const panelT = w * 0.022, panelH = h * 0.82, headerH = h * 0.12
      return (
        <group>
          {[-1, 1].map(sz => (
            <Slab key={sz} p={[0, bh/2, sz*(d/2 - fw/4)]} s={[w, bh, fw/2]} c={MC.base} m={0.7} r={0.3} />
          ))}
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*(w/2-pw/2), h*0.5, 0]} s={[pw, h*0.96, pw]} c={MC.frame} m={0.8} r={0.2} />
          ))}
          <Slab p={[0, bh + panelH*0.5, 0]} s={[w-pw*2, panelH, panelT]} c={MC.board} m={0.1} r={0.4} />
          <Slab p={[0, bh + panelH + headerH*0.5, 0]} s={[w, headerH, panelT*1.5]} c={MC.base} m={0.7} r={0.3} />
        </group>
      )
    }
    case 'end_cap_shelf': {
      // 엔드캡: 곤돌라 변형 + 상단 사인보드 헤더 강조
      const pw = w * 0.04, bh = h * 0.06, st = h * 0.013
      const sd = d * 0.88, headerH = h * 0.10, bodyH = h - headerH
      return (
        <group>
          <Slab p={[0, bh/2, 0]} s={[w, bh, d]} c={MC.base} m={0.7} r={0.3} />
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*(w/2-pw/2), bodyH/2, 0]} s={[pw, bodyH, d]} c={MC.frame} m={0.7} r={0.3} />
          ))}
          {[0.15, 0.35, 0.55, 0.73].map((f, i) => (
            <Slab key={i} p={[0, f*bodyH, 0]} s={[w-pw*2, st, sd]} c={MC.board} m={0.1} r={0.5} />
          ))}
          <Slab p={[0, h - headerH/2, 0]} s={[w, headerH, d*0.3]} c={MC.light} m={0.1} r={0.3} />
        </group>
      )
    }
    case 'tower_display': {
      // 타워: 4면 패널로 사각 기둥 구조 + 4단 내부 선반
      const side = w * 0.022, bh = h * 0.03, st = h * 0.012
      return (
        <group>
          <Slab p={[0, bh/2, 0]} s={[w, bh, d]} c={MC.base} m={0.7} r={0.3} />
          <Slab p={[0, h*0.5, -(d/2-side/2)]}  s={[w, h, side]} c={MC.frame} m={0.7} r={0.3} />
          <Slab p={[0, h*0.5,  (d/2-side/2)]}  s={[w, h, side]} c={MC.frame} m={0.7} r={0.3} />
          <Slab p={[-(w/2-side/2), h*0.5, 0]}  s={[side, h, d]} c={MC.frame} m={0.7} r={0.3} />
          <Slab p={[ (w/2-side/2), h*0.5, 0]}  s={[side, h, d]} c={MC.frame} m={0.7} r={0.3} />
          {[0.22, 0.42, 0.62, 0.82].map((f, i) => (
            <Slab key={i} p={[0, f*h, 0]} s={[w-side*2, st, d-side*2]} c={MC.board} m={0.1} r={0.5} />
          ))}
        </group>
      )
    }
    // ── 의자류 ────────────────────────────────────────────────────────────────
    case 'folding_chair': {
      // 접이식 의자: 4개 금속 다리 + 좌판 + 등받이
      const seatY = h * 0.51, legT = w * 0.044, st = h * 0.028
      return (
        <group>
          {[-1, 1].flatMap(sx =>
            [-1, 1].map(sz => (
              <Slab key={`${sx}${sz}`} p={[sx*w*0.38, seatY/2, sz*d*0.37]} s={[legT, seatY, legT]} c={MC.frame} m={0.8} r={0.2} />
            ))
          )}
          {/* 앞뒤 가로 보강바 */}
          {[-1, 1].map(sz => (
            <Slab key={sz} p={[0, seatY*0.28, sz*d*0.37]} s={[w*0.76, legT, legT]} c={MC.frame} m={0.8} r={0.2} />
          ))}
          {/* 좌판 */}
          <Slab p={[0, seatY, d*0.04]} s={[w*0.88, st, d*0.78]} c={MC.cushion} m={0.05} r={0.7} />
          {/* 등받이 */}
          <Slab p={[0, seatY + h*0.26, -d*0.41]} s={[w*0.88, h*0.44, st]} c={MC.cushion} m={0.05} r={0.7} />
        </group>
      )
    }
    case 'bar_stool': {
      // 바 스툴: 중앙 원형 기둥 + 상단 좌판 + 발판 링 + X자 베이스
      const seatY = h * 0.72, poleW = w * 0.10
      return (
        <group>
          {/* X자 베이스 */}
          {[0, Math.PI/2].map((rot, i) => (
            <mesh key={i} position={[0, h*0.014, 0]} rotation={[0, rot, 0]} receiveShadow castShadow>
              <boxGeometry args={[w*0.82, h*0.028, poleW]} />
              <meshStandardMaterial color={MC.frame} metalness={0.8} roughness={0.2} />
            </mesh>
          ))}
          {/* 중앙 기둥 */}
          <Slab p={[0, seatY*0.5, 0]} s={[poleW, seatY, poleW]} c={MC.frame} m={0.8} r={0.2} />
          {/* 발판 (십자) */}
          <Slab p={[0, h*0.28, 0]} s={[w*0.75, h*0.018, poleW]} c={MC.frame} m={0.8} r={0.2} />
          <Slab p={[0, h*0.28, 0]} s={[poleW, h*0.018, d*0.75]} c={MC.frame} m={0.8} r={0.2} />
          {/* 좌판 */}
          <Slab p={[0, seatY, 0]} s={[w*0.88, h*0.038, d*0.88]} c={MC.woodLight} m={0.1} r={0.5} />
        </group>
      )
    }
    case 'office_chair': {
      // 사무용 의자: 5발 베이스 + 기압식 기둥 + 두꺼운 쿠션 좌판 + 등받이 + 팔걸이
      const seatY = h * 0.40, colW = w * 0.07
      return (
        <group>
          {/* 5발 베이스 (X자 근사) */}
          {[0, Math.PI/2, Math.PI/4, -Math.PI/4].map((rot, i) => (
            <mesh key={i} position={[0, h*0.012, 0]} rotation={[0, rot, 0]} receiveShadow castShadow>
              <boxGeometry args={[w*0.85, h*0.024, colW]} />
              <meshStandardMaterial color={MC.base} metalness={0.8} roughness={0.2} />
            </mesh>
          ))}
          {/* 기압 기둥 */}
          <Slab p={[0, (h*0.024 + seatY)*0.5, 0]} s={[colW, seatY - h*0.024, colW]} c={MC.frame} m={0.7} r={0.3} />
          {/* 좌판 쿠션 */}
          <Slab p={[0, seatY, 0]} s={[w*0.82, h*0.085, d*0.82]} c={MC.leather} m={0.3} r={0.6} />
          {/* 등받이 */}
          <Slab p={[0, seatY + h*0.085*0.5 + h*0.24, -d*0.33]} s={[w*0.72, h*0.44, h*0.04]} c={MC.leather} m={0.3} r={0.6} />
          {/* 팔걸이 (좌우) */}
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*w*0.40, seatY + h*0.09, d*0.05]} s={[colW, h*0.04, d*0.30]} c={MC.base} m={0.7} r={0.3} />
          ))}
        </group>
      )
    }
    case 'lounge_chair': {
      // 라운지 의자: 블록형 다리 + 두꺼운 쿠션 좌판 + 등받이 + 사이드 팔걸이
      const legH = h * 0.27, legW = w * 0.065
      return (
        <group>
          {/* 4개 다리 */}
          {[-1, 1].flatMap(sx =>
            [-1, 1].map(sz => (
              <Slab key={`${sx}${sz}`} p={[sx*w*0.38, legH/2, sz*d*0.38]} s={[legW, legH, legW]} c={MC.wood} m={0.1} r={0.6} />
            ))
          )}
          {/* 좌판 쿠션 (두껍고 넓음) */}
          <Slab p={[0, legH + h*0.10, 0]} s={[w*0.80, h*0.20, d*0.72]} c={MC.fabric} m={0.05} r={0.8} />
          {/* 등받이 쿠션 */}
          <Slab p={[0, legH + h*0.1 + h*0.1 + h*0.24, -d*0.32]} s={[w*0.80, h*0.46, h*0.13]} c={MC.fabric} m={0.05} r={0.8} />
          {/* 팔걸이 (좌우) */}
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*w*0.43, legH + h*0.1 + h*0.10, -d*0.04]} s={[h*0.10, h*0.20, d*0.70]} c={MC.fabric} m={0.05} r={0.8} />
          ))}
        </group>
      )
    }
    case 'dining_chair': {
      // 다이닝 의자: 4개 나무 다리 + 좌판 + 등받이 수직 살대
      const seatY = h * 0.50, legT = w * 0.055
      return (
        <group>
          {/* 4개 다리 */}
          {[-1, 1].flatMap(sx =>
            [-1, 1].map(sz => (
              <Slab key={`${sx}${sz}`} p={[sx*w*0.38, seatY/2, sz*d*0.38]} s={[legT, seatY, legT]} c={MC.wood} m={0.05} r={0.6} />
            ))
          )}
          {/* 좌판 */}
          <Slab p={[0, seatY, 0]} s={[w*0.90, h*0.028, d*0.85]} c={MC.woodLight} m={0.05} r={0.5} />
          {/* 등받이 수직 기둥 (×2) */}
          {[-1, 1].map(sx => (
            <Slab key={sx} p={[sx*w*0.38, seatY + h*0.25, -d*0.38]} s={[legT, h*0.50, legT]} c={MC.wood} m={0.05} r={0.6} />
          ))}
          {/* 등받이 수평 살대 (×3) */}
          {[0.17, 0.30, 0.43].map((f, i) => (
            <Slab key={i} p={[0, seatY + f*h, -d*0.36]} s={[w*0.76, h*0.022, legT]} c={MC.woodLight} m={0.05} r={0.5} />
          ))}
        </group>
      )
    }
    default:
      return null
  }
}

function ResizeHandle({ position, axis, obj, onResize }: {
  position: [number, number, number]; axis: "w+" | "w-" | "d+" | "d-"
  obj: LayoutObject; onResize: (id: string, changes: Partial<LayoutObject>) => void
}) {
  const [dragging, setDragging] = useState(false)
  const [hovered, setHovered] = useState(false)
  const dragRef = useRef({ active: false, prev: 0, accum: 0, objId: "", isW: false, sign: 1 })
  const isW = axis.startsWith("w")
  const sign = axis.endsWith("+") ? 1 : -1

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const d = dragRef.current
      if (!d.active) return
      const current = d.isW ? e.clientX : e.clientY
      const pxDelta = current - d.prev
      d.prev = current
      d.accum += pxDelta * 3 * d.sign * (d.isW ? 1 : -1)
      if (Math.abs(d.accum) >= 50) {
        const steps = Math.trunc(d.accum / 50)
        d.accum -= steps * 50
        const currentSize = d.isW ? obj.width_mm : obj.depth_mm
        const newSize = Math.max(100, currentSize + steps * 50)
        onResize(d.objId, d.isW ? { width_mm: newSize } : { depth_mm: newSize })
      }
    }
    const onUp = () => { if (!dragRef.current.active) return; dragRef.current.active = false; setDragging(false); setHovered(false) }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp) }
  }, [obj.width_mm, obj.depth_mm, obj.id, onResize])

  return (
    <mesh position={position}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => { if (!dragging) setHovered(false) }}
      onPointerDown={(e) => {
        if (e.nativeEvent.ctrlKey) return; e.stopPropagation(); setDragging(true)
        dragRef.current = { active: true, prev: isW ? e.nativeEvent.clientX : e.nativeEvent.clientY, accum: 0, objId: obj.id, isW, sign }
      }}>
      <sphereGeometry args={[0.12, 12, 12]} />
      <meshBasicMaterial color={dragging ? "#f59e0b" : hovered ? "#818cf8" : "#6366f1"} transparent opacity={dragging ? 0.95 : hovered ? 0.9 : 0.7} />
    </mesh>
  )
}

function FloorDragPlane({ onDragMove }: { onDragMove: (worldX: number, worldZ: number) => void }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.001, 0]} visible={false}
      onPointerMove={(e) => { e.stopPropagation(); onDragMove(e.point.x, e.point.z) }}>
      <planeGeometry args={[500, 500]} />
      <meshBasicMaterial />
    </mesh>
  )
}

function PlacedObject({ obj, selected, onClick, onResize, hasCollision, onStartDrag, onStartRotate }: {
  obj: LayoutObject; selected?: boolean; onClick?: () => void
  onResize?: (id: string, changes: Partial<LayoutObject>) => void
  hasCollision?: boolean; onStartDrag?: (objId: string, offsetX: number, offsetZ: number) => void
  onStartRotate?: (objId: string, clientX: number, currentAngle: number) => void
}) {
  const cfg = OBJ_CFG[obj.object_type] ?? OBJ_DEFAULT
  const w = obj.width_mm * MM, d = obj.depth_mm * MM, h = (obj.height_mm ?? cfg.h * 1000) * MM
  // center_x_mm/center_y_mm 를 그대로 사용 (top-left 변환 X)
  const x = obj.center_x_mm * MM, z = obj.center_y_mm * MM
  const rad = (obj.rotation_deg * Math.PI) / 180
  const faceColor = hasCollision ? "#fca5a5" : cfg.color
  const edgeColorFinal = hasCollision ? "#dc2626" : (selected ? "#f59e0b" : cfg.edgeColor)
  const labelColor = hasCollision ? "#dc2626" : (selected ? "#f59e0b" : cfg.edgeColor)
  const label = obj.label ?? obj.object_type.replace(/_/g, " ")
  const edgesGeo = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d)), [w, h, d])
  const modelPath = MODEL_PATHS[obj.object_type]

  const boxMesh = (
    <mesh receiveShadow castShadow position={[0, h / 2, 0]}>
      <boxGeometry args={[w, h, d]} />
      <meshStandardMaterial color={faceColor} roughness={0.85} metalness={0} transparent={false} depthWrite={true} depthTest={true} />
    </mesh>
  )
  // 프로시져럴 모델이 있는 기물은 GLB 없이도 실물 형태 표현. GLB 로드 성공 시 GLB 우선.
  const defaultVisual = modelPath !== undefined
    ? <ProceduralShelfModel type={obj.object_type} w={w} h={h} d={d} />
    : boxMesh

  return (
    <group position={[x, 0, z]} rotation={[0, -rad, 0]}
      onClick={(e) => { e.stopPropagation(); debugLog({ event: 'object_click', type: obj.object_type, id: obj.id, was_selected: selected }); onClick?.(); }}
      onPointerDown={(e) => {
        if (e.nativeEvent.ctrlKey) return; e.stopPropagation()
        if (onStartRotate) { onStartRotate(obj.id, e.nativeEvent.clientX, obj.rotation_deg ?? 0); return }
        if (!selected) return
        onStartDrag?.(obj.id, e.point.x - x, e.point.z - z)
      }}>
      {modelPath ? (
        <ModelErrorBoundary fallback={defaultVisual}>
          <Suspense fallback={defaultVisual}>
            <GlbModel path={modelPath} w={w} h={h} d={d} />
          </Suspense>
        </ModelErrorBoundary>
      ) : defaultVisual}
      {(!modelPath || selected) && (
        <lineSegments geometry={edgesGeo} position={[0, h / 2, 0]}>
          <lineBasicMaterial color={edgeColorFinal} linewidth={selected ? 2 : 1} />
        </lineSegments>
      )}
      {selected && (
        <mesh position={[0, h / 2, 0]}>
          <boxGeometry args={[w + 0.02, h + 0.02, d + 0.02]} />
          <meshBasicMaterial color="#f59e0b" transparent opacity={0.15} depthWrite={false} />
        </mesh>
      )}
      {/* 기물 상단 라벨 — drei <Text> 는 troika SDF 쉐이더 사용, GLB export 시 글자 증발하고 빈 사각형만 남음. excludeFromGlb 태그로 export 제외 */}
      <group userData={{ excludeFromGlb: true }}>
        <Text position={[0, h + 0.15, 0]} fontSize={0.22} color={labelColor} anchorX="center" anchorY="bottom" outlineWidth={0.02} outlineColor="#ffffff">
          {label}
        </Text>
      </group>
      {selected && onResize && (
        <>
          <ResizeHandle position={[w / 2, 0.06, 0]} axis="w+" obj={obj} onResize={onResize} />
          <ResizeHandle position={[-w / 2, 0.06, 0]} axis="w-" obj={obj} onResize={onResize} />
          <ResizeHandle position={[0, 0.06, d / 2]} axis="d+" obj={obj} onResize={onResize} />
          <ResizeHandle position={[0, 0.06, -d / 2]} axis="d-" obj={obj} onResize={onResize} />
        </>
      )}
    </group>
  )
}

const DEAD_ZONE_LABEL: Record<string, string> = { sprinkler: "SP", fire_hydrant: "FH", electrical_panel: "EP", core: "화장실", toilet: "TO", stair: "ST", pillar: "기둥", core_access: "진입로", inner_wall: "내벽", emergency_exit: "비상구" }
const DEAD_ZONE_NAME: Record<string, string> = { sprinkler: "스프링클러", fire_hydrant: "소화전", electrical_panel: "분전반", core: "화장실/계단", toilet: "화장실", stair: "계단", pillar: "기둥", core_access: "진입로 확보", inner_wall: "내벽", emergency_exit: "비상구" }

function DeadZoneDisk({ center, radius, type, index, polygon }: { center: number[]; radius: number; type: string; index?: number; polygon?: number[][] }) {
  // EP는 dot 좌표(polygon 첫 점)를 라벨 위치로 사용. 다른 타입은 centroid.
  const labelPt = (type === "electrical_panel" && polygon && polygon.length >= 1) ? polygon[0] : center
  const r = radius * MM, cx = labelPt[0] * MM, cz = labelPt[1] * MM
  const label = DEAD_ZONE_LABEL[type] ?? type.slice(0, 2).toUpperCase()
  const name = DEAD_ZONE_NAME[type] ?? type
  const indexLabel = index !== undefined ? `${label}#${index + 1}` : label

  const isEP = type === "electrical_panel"
  // 구조물(core/pillar/화장실/계단/내벽)은 3D extrude, EP는 wireframe+바닥, 설비(소화전)는 바닥 원형
  const usePolygon = polygon && polygon.length >= 3 && ["core", "toilet", "stair", "pillar", "core_access", "inner_wall", "electrical_panel"].includes(type)
  const WALL_HEIGHT = 3000 * MM  // 천장고 3000mm

  const extrudeGeo = useMemo(() => {
    if (usePolygon && polygon && polygon.length >= 3) {
      const shape = new THREE.Shape()
      polygon.forEach((pt, i) => {
        if (i === 0) shape.moveTo(pt[0] * MM, -pt[1] * MM)
        else shape.lineTo(pt[0] * MM, -pt[1] * MM)
      })
      shape.closePath()
      return new THREE.ExtrudeGeometry(shape, { depth: isEP ? 0.01 : WALL_HEIGHT, bevelEnabled: false })
    }
    return null
  }, [polygon, usePolygon, isEP, WALL_HEIGHT])

  // EP용 바닥 polygon + wireframe 수직선
  const epFloorGeo = useMemo(() => {
    if (!isEP || !polygon || polygon.length < 3) return null
    const shape = new THREE.Shape()
    polygon.forEach((pt, i) => {
      if (i === 0) shape.moveTo(pt[0] * MM, -pt[1] * MM)
      else shape.lineTo(pt[0] * MM, -pt[1] * MM)
    })
    shape.closePath()
    return new THREE.ShapeGeometry(shape)
  }, [polygon, isEP])

  // EP 수직 wireframe 라인 (각 꼭짓점에서 천장까지)
  const epEdgeLines = useMemo(() => {
    if (!isEP || !polygon || polygon.length < 3) return null
    const lines: THREE.Vector3[][] = []
    // 바닥 외곽선
    const floorPts = polygon.map(pt => new THREE.Vector3(pt[0] * MM, 0.01, pt[1] * MM))
    floorPts.push(floorPts[0].clone())
    lines.push(floorPts)
    // 천장 외곽선
    const ceilPts = polygon.map(pt => new THREE.Vector3(pt[0] * MM, WALL_HEIGHT, pt[1] * MM))
    ceilPts.push(ceilPts[0].clone())
    lines.push(ceilPts)
    // 수직선 (각 꼭짓점)
    polygon.forEach(pt => {
      lines.push([
        new THREE.Vector3(pt[0] * MM, 0.01, pt[1] * MM),
        new THREE.Vector3(pt[0] * MM, WALL_HEIGHT, pt[1] * MM),
      ])
    })
    return lines
  }, [polygon, isEP])

  // 구조물 타입별 색상
  const wallColor = type === "stair" ? "#94a3b8" : type === "toilet" ? "#d1d5db" : type === "pillar" ? "#a8a29e" : type === "electrical_panel" ? "#7c3aed" : "#e2e8f0"
  const wallOpacity = 0.4

  return (
    <group position={extrudeGeo && !isEP ? [0, 0, 0] : [0, 0, 0]}>
      {isEP && epFloorGeo ? (
        <>
          {/* EP: 바닥 반투명 fill */}
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.008, 0]}>
            <primitive object={epFloorGeo} />
            <meshBasicMaterial color="#7c3aed" transparent opacity={0.15} depthWrite={false} />
          </mesh>
          {/* EP: wireframe 박스 (수직선 + 외곽선) */}
          {epEdgeLines?.map((pts, i) => (
            <Line key={i} points={pts.map(p => [p.x, p.y, p.z] as [number, number, number])} color="#7c3aed" lineWidth={1.5} transparent opacity={0.6} />
          ))}
        </>
      ) : extrudeGeo ? (
        <mesh rotation={[-Math.PI / 2, 0, 0]}>
          <primitive object={extrudeGeo} />
          <meshStandardMaterial color={wallColor} transparent={true} opacity={wallOpacity} depthWrite={false} depthTest={true} side={THREE.FrontSide} roughness={0.8} />
        </mesh>
      ) : (
        <>
          <mesh position={[cx, 0.003, cz]} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[r, 48]} />
            <meshBasicMaterial color="#ef4444" transparent opacity={0.12} depthWrite={false} />
          </mesh>
          <mesh position={[cx, 0.005, cz]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[r * 0.94, r, 48]} />
            <meshBasicMaterial color="#ef4444" transparent opacity={0.55} depthWrite={false} />
          </mesh>
        </>
      )}
      {/* drei Text = troika 커스텀 쉐이더 → GLTFExporter 직렬화 불가. excludeFromGlb 로 반드시 제외 */}
      <group userData={{ excludeFromGlb: true }}>
        {/* @ts-expect-error depthTest는 Three.js material prop */}
        <Text position={[cx, WALL_HEIGHT + 0.1, cz]} fontSize={r > 0 ? r * 0.32 : 0.3} color="#dc2626" anchorX="center" anchorY="middle" outlineWidth={0.015} outlineColor="#ffffff" renderOrder={10} depthTest={false}>{indexLabel}</Text>
        {/* @ts-expect-error depthTest는 Three.js material prop */}
        <Text position={[cx, WALL_HEIGHT + 0.02, cz + (r > 0 ? r * 0.18 : 0.15)]} fontSize={r > 0 ? r * 0.18 : 0.15} color="#ef4444" anchorX="center" anchorY="top" outlineWidth={0.01} outlineColor="#ffffff" renderOrder={10} depthTest={false}>{name}</Text>
      </group>
    </group>
  )
}

function EntranceMarker({ x, y, x2, y2, pointsMm, confidence }: {
  x: number; y: number; x2?: number | null; y2?: number | null
  pointsMm?: Array<{ x_mm: number; y_mm: number }>; confidence?: string
}) {
  const isEstimated = confidence === "default" || confidence === "low"
  const label = isEstimated ? "입구(추정)" : "입구"
  const color = isEstimated ? "#f59e0b" : "#22c55e"
  const emissive = isEstimated ? "#f59e0b" : "#22c55e"
  const textColor = isEstimated ? "#d97706" : "#16a34a"
  const pts = pointsMm && pointsMm.length >= 2 ? pointsMm : null

  if (pts) {
    const mx = pts.reduce((s, p) => s + p.x_mm, 0) / pts.length * MM
    const mz = pts.reduce((s, p) => s + p.y_mm, 0) / pts.length * MM
    return (
      <group>
        {pts.map((p, i) => { if (i === 0) return null; const prev = pts[i-1]; const sx=((prev.x_mm+p.x_mm)/2)*MM; const sz=((prev.y_mm+p.y_mm)/2)*MM; const dx=(p.x_mm-prev.x_mm)*MM; const dz=(p.y_mm-prev.y_mm)*MM; const len=Math.hypot(dx,dz); const angle=Math.atan2(dz,dx); return (<mesh key={i} position={[sx,0.01,sz]} rotation={[-Math.PI/2,0,-angle]}><planeGeometry args={[len,0.15]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.4}/></mesh>) })}
        {pts.map((p, i) => (<mesh key={`pt${i}`} position={[p.x_mm*MM,0.02,p.y_mm*MM]} rotation={[-Math.PI/2,0,0]}><circleGeometry args={[0.15,24]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.5}/></mesh>))}
        <Text position={[mx,0.25,mz]} fontSize={0.18} color={textColor} anchorX="center" outlineWidth={0.015} outlineColor="#ffffff">{label}</Text>
      </group>
    )
  }
  if (x2 != null && y2 != null) {
    const mx=((x+x2)/2)*MM; const mz=((y+y2)/2)*MM; const dx=(x2-x)*MM; const dz=(y2-y)*MM; const len=Math.hypot(dx,dz); const angle=Math.atan2(dz,dx)
    return (<group><mesh position={[mx,0.01,mz]} rotation={[-Math.PI/2,0,-angle]}><planeGeometry args={[len,0.15]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.4}/></mesh><mesh position={[x*MM,0.02,y*MM]} rotation={[-Math.PI/2,0,0]}><circleGeometry args={[0.15,24]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.5}/></mesh><mesh position={[x2*MM,0.02,y2*MM]} rotation={[-Math.PI/2,0,0]}><circleGeometry args={[0.15,24]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.5}/></mesh><Text position={[mx,0.25,mz]} fontSize={0.18} color={textColor} anchorX="center" outlineWidth={0.015} outlineColor="#ffffff">{label}</Text></group>)
  }
  return (
    <group position={[x*MM,0,y*MM]}>
      <mesh position={[0,0.02,0]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[0.22,0.38,36]}/><meshStandardMaterial color={color} emissive={emissive} emissiveIntensity={0.5}/></mesh>
      <Text position={[0,0.2,0]} fontSize={0.16} color={textColor} anchorX="center" outlineWidth={0.015} outlineColor="#ffffff">{label}</Text>
    </group>
  )
}

const FLOOR_PATTERNS: Record<string, { label: string; tileM: number }> = {
  wood:      { label: '원목',    tileM: 0.9 },
  tile:      { label: '타일',    tileM: 0.6 },
  concrete:  { label: '콘크리트', tileM: 2.0 },
  terrazzo:  { label: '테라조',  tileM: 1.2 },
  marble:    { label: '대리석',  tileM: 1.8 },
}

function createFloorTexture(key: string): THREE.CanvasTexture {
  const S = 512
  const canvas = document.createElement('canvas')
  canvas.width = S; canvas.height = S
  const ctx = canvas.getContext('2d')!

  if (key === 'wood') {
    const plankH = 64
    const colors = ['#c8a882', '#bf9e78', '#d2b48c', '#c4a070']
    for (let y = 0; y < S; y += plankH) {
      ctx.fillStyle = colors[Math.floor(y / plankH) % colors.length]
      ctx.fillRect(0, y, S, plankH)
      ctx.strokeStyle = 'rgba(120,80,40,0.12)'; ctx.lineWidth = 1
      for (let g = 0; g < 8; g++) {
        const gy = y + g * (plankH / 8)
        ctx.beginPath(); ctx.moveTo(0, gy + Math.sin(g) * 3)
        for (let x = 0; x <= S; x += 20) ctx.lineTo(x, gy + Math.sin(x * 0.05 + g) * 3)
        ctx.stroke()
      }
      ctx.strokeStyle = 'rgba(90,60,30,0.3)'; ctx.lineWidth = 1.5
      ctx.strokeRect(0, y, S, plankH)
    }
  } else if (key === 'tile') {
    // 타일면 — 약한 크림색으로 구분감 부여
    ctx.fillStyle = '#ececec'; ctx.fillRect(0, 0, S, S)
    const t = 128
    // 타일 안쪽 하이라이트 (면마다 살짝 밝게)
    for (let x = 0; x < S; x += t) {
      for (let y = 0; y < S; y += t) {
        ctx.fillStyle = '#f4f4f4'
        ctx.fillRect(x + 2, y + 2, t - 4, t - 4)
      }
    }
    // 줄눈 — 확실히 어둡게
    ctx.strokeStyle = '#8a8a8a'; ctx.lineWidth = 4
    for (let x = 0; x <= S; x += t) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, S); ctx.stroke() }
    for (let y = 0; y <= S; y += t) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(S, y); ctx.stroke() }
  } else if (key === 'concrete') {
    ctx.fillStyle = '#d4d4d4'; ctx.fillRect(0, 0, S, S)
    for (let i = 0; i < 4000; i++) {
      const v = Math.floor(Math.random() * 40) - 20; const b = 212 + v
      ctx.fillStyle = `rgb(${b},${b},${b})`
      ctx.beginPath(); ctx.arc(Math.random() * S, Math.random() * S, Math.random() * 1.5, 0, Math.PI * 2); ctx.fill()
    }
  } else if (key === 'terrazzo') {
    ctx.fillStyle = '#e8e0d8'; ctx.fillRect(0, 0, S, S)
    const sc = ['#c0392b','#2980b9','#27ae60','#f39c12','#8e44ad','#2c3e50','#d35400']
    for (let i = 0; i < 220; i++) {
      ctx.save(); ctx.translate(Math.random() * S, Math.random() * S); ctx.rotate(Math.random() * Math.PI)
      ctx.globalAlpha = 0.6 + Math.random() * 0.4
      ctx.fillStyle = sc[Math.floor(Math.random() * sc.length)]
      ctx.beginPath(); ctx.ellipse(0, 0, 3 + Math.random() * 12, 2 + Math.random() * 8, 0, 0, Math.PI * 2); ctx.fill()
      ctx.restore()
    }
    ctx.globalAlpha = 1
  } else if (key === 'marble') {
    // 베이스: 약간 따뜻한 회백색
    ctx.fillStyle = '#eae6e0'; ctx.fillRect(0, 0, S, S)
    const drawVein = (x1: number, y1: number, cx1: number, cy1: number, cx2: number, cy2: number, x2: number, y2: number, w: number, c: string) => {
      ctx.strokeStyle = c; ctx.lineWidth = w
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.bezierCurveTo(cx1, cy1, cx2, cy2, x2, y2); ctx.stroke()
    }
    // 주요 결 — 불투명도 높게, 선 굵게
    drawVein(0, 100, 150, 80, 350, 200, 512, 180, 4, 'rgba(110,100,90,0.85)')
    drawVein(0, 300, 200, 250, 350, 350, 512, 400, 3, 'rgba(130,115,100,0.8)')
    drawVein(100, 0, 80, 200, 200, 350, 150, 512, 2.5, 'rgba(90,80,70,0.75)')
    drawVein(350, 0, 380, 150, 450, 300, 400, 512, 3.5, 'rgba(120,105,95,0.8)')
    drawVein(0, 450, 250, 420, 400, 480, 512, 460, 2, 'rgba(140,125,110,0.7)')
    // 가는 보조 결
    drawVein(50, 0, 100, 150, 200, 300, 180, 512, 1, 'rgba(100,90,80,0.5)')
    drawVein(0, 200, 100, 180, 300, 250, 512, 280, 1, 'rgba(115,105,95,0.45)')
  }

  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping
  return tex
}

function FloorShape({ polygon, textureKey }: { polygon: number[][], textureKey?: string | null }) {
  const geometry = useMemo(() => {
    const shape = new THREE.Shape()
    polygon.forEach((pt, i) => { if (i === 0) shape.moveTo(pt[0]*MM, -pt[1]*MM); else shape.lineTo(pt[0]*MM, -pt[1]*MM) })
    shape.closePath()
    return new THREE.ShapeGeometry(shape)
  }, [polygon])

  const texture = useMemo(() => {
    if (!textureKey) return null
    const tex = createFloorTexture(textureKey)
    // ShapeGeometry UV = 버텍스 좌표 그대로 (meters 단위). repeat = 1/tileM 으로 설정해야
    // 1m당 1/tileM 번 반복 → tileM 미터마다 한 타일.
    // wM/tileM 로 잘못 계산하면 수십~수백 번 반복되어 단색으로 보임.
    const tileM = FLOOR_PATTERNS[textureKey]?.tileM ?? 1.0
    tex.repeat.set(1 / tileM, 1 / tileM)
    return tex
  }, [textureKey])

  useEffect(() => () => { texture?.dispose() }, [texture])

  return (
    <mesh rotation={[-Math.PI/2,0,0]} receiveShadow userData={{ isFloor: true }}>
      <primitive object={geometry}/>
      {/* key 변경으로 textureKey 바뀔 때 material 강제 재생성 — r3f 가 기존 인스턴스 재사용 시
          map 추가에 needsUpdate 가 누락되는 케이스 방지 */}
      <meshStandardMaterial
        key={textureKey ?? 'default'}
        map={texture ?? undefined}
        color={texture ? '#ffffff' : '#f8fafc'}
        roughness={texture ? 0.85 : 0.95}
      />
    </mesh>
  )
}

// zone 바닥 색칠 — 구역을 나누듯 표현
const ZONE_COLORS: Record<string, string> = {
  entrance_zone: "#bbf7d0",  // 초록 (밝은)
  mid_zone: "#fef08a",       // 노랑 (밝은)
  deep_zone: "#bfdbfe",      // 파랑 (밝은)
}

const ZONE_BORDER_COLORS: Record<string, string> = {
  entrance_zone: "#22c55e",
  mid_zone: "#eab308",
  deep_zone: "#3b82f6",
}

// 2026-05-01 Phase 4 — concept_area 색 (large 8 영역, 영문 키 — DB/state/응답 통일)
const CONCEPT_AREA_COLORS: Record<string, string> = {
  welcome: "#fef3c7",      // amber (맞이)
  photo: "#fce7f3",        // pink (포토)
  experience: "#cffafe",   // cyan (체험)
  screening: "#e9d5ff",    // purple (상영)
  retail: "#fed7aa",       // orange (굿즈판매)
  checkout: "#cbd5e1",     // slate (결제)
  hybrid: "#bbf7d0",       // green (혼합)
  lounge: "#fde68a",       // yellow (휴식)
}

export const CONCEPT_AREA_BORDER_COLORS: Record<string, string> = {
  welcome: "#f59e0b",
  photo: "#ec4899",
  experience: "#06b6d4",
  screening: "#a855f7",
  retail: "#f97316",
  checkout: "#64748b",
  hybrid: "#22c55e",
  lounge: "#eab308",
}

// 2026-05-01 Phase 4-2 갈래 3 — 영문 키 → 한국어 라벨 (레전드 표시 / Viewer 라벨용).
// 백엔드 nodes_large/concept_area.py CONCEPT_AREA_LABEL_KO 와 정합.
export const CONCEPT_AREA_LABEL_KO: Record<string, string> = {
  welcome: "맞이",
  photo: "포토",
  experience: "체험",
  screening: "상영",
  retail: "굿즈판매",
  checkout: "결제",
  hybrid: "혼합",
  lounge: "휴식",
}
const ZONE_HEIGHTS: Record<string, number> = {
  entrance_zone: 0.008,
  mid_zone: 0.006,
  deep_zone: 0.004,
}

function ZoneFloors({ zoneMap, visibleKeys }: { zoneMap?: Record<string, { polygon_mm: number[][]; reference_points?: string[] }>; visibleKeys?: Set<string> }) {
  if (!zoneMap) return null
  return (
    <group>
      {Object.entries(zoneMap).map(([zoneName, zoneData]) => {
        if (visibleKeys && !visibleKeys.has(zoneName)) return null
        const poly = zoneData.polygon_mm
        if (!poly || poly.length < 3) return null
        const shape = new THREE.Shape()
        poly.forEach((pt: number[], i: number) => {
          if (i === 0) shape.moveTo(pt[0] * MM, -pt[1] * MM)
          else shape.lineTo(pt[0] * MM, -pt[1] * MM)
        })
        shape.closePath()
        const geo = new THREE.ShapeGeometry(shape)
        const fillColor = ZONE_COLORS[zoneName] || "#e2e8f0"
        const borderColor = ZONE_BORDER_COLORS[zoneName] || "#94a3b8"
        const yPos = ZONE_HEIGHTS[zoneName] || 0.004

        // 등고선 (외곽선)
        const linePoints: THREE.Vector3[] = poly.map((pt: number[]) =>
          new THREE.Vector3(pt[0] * MM, yPos + 0.001, pt[1] * MM)
        )
        if (linePoints.length > 0) linePoints.push(linePoints[0].clone())
        const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints)

        return (
          <group key={zoneName}>
            {/* 채우기 */}
            <mesh geometry={geo} rotation={[-Math.PI / 2, 0, 0]} position={[0, yPos, 0]}>
              <meshBasicMaterial color={fillColor} transparent opacity={0.18} depthWrite={false} />
            </mesh>
            {/* 등고선 */}
            <lineLoop geometry={lineGeo}>
              <lineBasicMaterial color={borderColor} linewidth={2} transparent opacity={0.7} />
            </lineLoop>
          </group>
        )
      })}
    </group>
  )
}

// 2026-05-01 Phase 4-2 갈래 3 — concept_area 폴리곤 채우기 (영역별 바닥색 + 등고선 + 라벨).
// ZoneFloors 패턴 차용. 응답 concept_areas: [{name(EN), polygon_mm: [[x,y],...], area_ratio}, ...]
// y=0.005 (ZoneFloors 의 0.004~0.008 사이) — 위/아래 stacking 을 피해 도면 위에 살짝 떠 있음.
function ConceptAreaFloors({ areas, visibleKeys }: { areas?: { name: string; polygon_mm: number[][]; area_ratio?: number }[]; visibleKeys?: Set<string> }) {
  if (!areas || areas.length === 0) return null
  return (
    <group>
      {areas.map((area, idx) => {
        if (visibleKeys && !visibleKeys.has(area.name)) return null
        const poly = area.polygon_mm
        if (!poly || poly.length < 3) return null
        const shape = new THREE.Shape()
        poly.forEach((pt: number[], i: number) => {
          if (i === 0) shape.moveTo(pt[0] * MM, -pt[1] * MM)
          else shape.lineTo(pt[0] * MM, -pt[1] * MM)
        })
        shape.closePath()
        const geo = new THREE.ShapeGeometry(shape)
        const fillColor = CONCEPT_AREA_COLORS[area.name] || "#e2e8f0"
        const borderColor = CONCEPT_AREA_BORDER_COLORS[area.name] || "#94a3b8"
        const labelKo = CONCEPT_AREA_LABEL_KO[area.name] || area.name
        const yPos = 0.005

        // ZoneFloors 와 동일 좌표계 — mesh 는 -pt[1] 후 -π/2 회전, line/Text 는 회전 안 하므로 +pt[1]
        const linePoints: THREE.Vector3[] = poly.map((pt: number[]) =>
          new THREE.Vector3(pt[0] * MM, yPos + 0.001, pt[1] * MM)
        )
        if (linePoints.length > 0) linePoints.push(linePoints[0].clone())
        const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints)

        // 영역 라벨 위치 — polygon centroid (간단 평균)
        const cx = poly.reduce((s, p) => s + p[0], 0) / poly.length
        const cy = poly.reduce((s, p) => s + p[1], 0) / poly.length

        return (
          <group key={`concept-${idx}-${area.name}`}>
            <mesh geometry={geo} rotation={[-Math.PI / 2, 0, 0]} position={[0, yPos, 0]}>
              <meshBasicMaterial color={fillColor} transparent opacity={0.32} depthWrite={false} />
            </mesh>
            <lineLoop geometry={lineGeo}>
              <lineBasicMaterial color={borderColor} linewidth={2} transparent opacity={0.85} />
            </lineLoop>
            <Text
              position={[cx * MM, yPos + 0.05, cy * MM]}
              fontSize={0.22}
              color={borderColor}
              anchorX="center"
              anchorY="middle"
              outlineWidth={0.02}
              outlineColor="#ffffff"
            >
              {labelKo}
            </Text>
          </group>
        )
      })}
    </group>
  )
}

function MainArteryLine({ coords, mode }: { coords?: number[][] | null; mode: 'arrow' | 'buffer' | 'off' }) {
  const points = useMemo(() => (coords && coords.length >= 2) ? coords.map(c => [c[0] * MM, 0.015, c[1] * MM] as [number, number, number]) : [], [coords])

  // buffer 모드: 주동선 양쪽 450mm(합 900mm) 반투명 폴리곤
  const bufferGeo = useMemo(() => {
    if (mode !== 'buffer' || !coords || coords.length < 2) return null
    const HALF_W = 450 * MM  // 주동선 반폭
    const shape = new THREE.Shape()
    // 단순 직선 경로 → 양쪽으로 확장
    for (let i = 0; i < coords.length; i++) {
      const x = coords[i][0] * MM, z = -coords[i][1] * MM
      if (i === 0) shape.moveTo(x - HALF_W, z)
      else shape.lineTo(x - HALF_W, z)
    }
    for (let i = coords.length - 1; i >= 0; i--) {
      const x = coords[i][0] * MM, z = -coords[i][1] * MM
      shape.lineTo(x + HALF_W, z)
    }
    shape.closePath()
    return new THREE.ShapeGeometry(shape)
  }, [coords, mode])

  if (mode === 'off' || !coords || coords.length < 2) return null

  return (
    <group>
      {mode === 'arrow' && (
        <>
          <Line points={points} color="#f59e0b" lineWidth={2.5} transparent opacity={0.8} />
          {/* 방향 화살표들 */}
          {points.length >= 2 && Array.from({ length: Math.min(3, points.length - 1) }, (_, i) => {
            const idx = Math.floor((i + 1) * (points.length - 1) / 4)
            return (
              <mesh key={i} position={[points[idx][0], 0.02, points[idx][2]]} rotation={[-Math.PI / 2, 0, 0]}>
                <circleGeometry args={[0.08, 3]} />
                <meshBasicMaterial color="#f59e0b" transparent opacity={0.7} />
              </mesh>
            )
          })}
        </>
      )}
      {mode === 'buffer' && bufferGeo && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.005, 0]}>
          <primitive object={bufferGeo} />
          <meshBasicMaterial color="#f59e0b" transparent opacity={0.12} depthWrite={false} />
        </mesh>
      )}
    </group>
  )
}

// 2026-04-29 (#116, F-8 복원): 부동선 (sub_path) 시각화.
// MainArteryLine 패턴 차용. 색상 구분 — main=황색(#f59e0b), sub=청색(#60a5fa).
// 점선 / 약간 옅은 opacity 로 보조 동선 의미 강조.
// y=0.016: MainArteryLine(0.015) 바로 위. depth 묻힘 방지 + renderOrder=3 으로 z-sort 우위 확보.
function SubPathLine({ coords }: { coords?: number[][] | null }) {
  const points = useMemo(
    () => (coords && coords.length >= 2)
      ? coords.map(c => [c[0] * MM, 0.016, c[1] * MM] as [number, number, number])
      : [],
    [coords],
  )
  if (!coords || coords.length < 2) return null
  return (
    <Line
      points={points}
      color="#60a5fa"
      lineWidth={3}
      dashed
      dashScale={1}
      dashSize={0.15}
      gapSize={0.08}
      transparent
      opacity={0.95}
      depthTest={false}
      renderOrder={3}
    />
  )
}

// 2026-05-04 신설 - 여러 가지 (sub_path branches) wrapper.
// 형식 변경 - 단일 라인 number[][] (옛) -> 여러 라인 number[][][] (신, 가지 형태).
// 각 가지 = 별 SubPathLine. main_artery 에서 좁은 영역 / 고립 ref_point 까지 일자 동선.
function SubPathBranches({ branches }: { branches?: number[][][] | null }) {
  if (!branches || branches.length === 0) return null
  return (
    <group>
      {branches.map((branch, i) => (
        <SubPathLine key={`subpath_branch_${i}`} coords={branch} />
      ))}
    </group>
  )
}

function ReferencePointMarkers({ refPoints }: { refPoints?: Record<string, { x_mm: number; y_mm: number; zone_label?: string; concept_area?: string; facing_entrance?: boolean; is_entrance_wall?: boolean; wall_size_label?: string }> }) {
  if (!refPoints) return null
  return (
    <group>
      {Object.entries(refPoints).map(([key, rp]) => {
        const x = rp.x_mm * MM, z = rp.y_mm * MM
        // 2026-05-01 Phase 4 — concept_area (한국어 large) 우선, zone_label (small) fallback
        const conceptColor = rp.concept_area ? CONCEPT_AREA_BORDER_COLORS[rp.concept_area] : null
        const zone = rp.zone_label || "mid_zone"
        const color = conceptColor || ZONE_BORDER_COLORS[zone] || "#94a3b8"
        const size = rp.wall_size_label === "\ub113\uc740 \ubcbd" ? 0.15 : rp.wall_size_label === "\ubcf4\ud1b5 \ubcbd" ? 0.10 : 0.07
        return (
          <group key={key} position={[x, 0.02, z]}>
            {/* 다이아몬드 마커 */}
            <mesh rotation={[-Math.PI / 2, Math.PI / 4, 0]}>
              <planeGeometry args={[size, size]} />
              <meshBasicMaterial color={color} transparent opacity={0.8} depthWrite={false} />
            </mesh>
            {/* 외곽선 */}
            <mesh rotation={[-Math.PI / 2, Math.PI / 4, 0]}>
              <planeGeometry args={[size + 0.02, size + 0.02]} />
              <meshBasicMaterial color="#ffffff" transparent opacity={0.5} depthWrite={false} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}

function SlotMarkers({ slots }: { slots?: Record<string, { x_mm: number; y_mm: number; zone_label?: string; concept_area?: string; wall_size_label?: string }> }) {
  if (!slots) return null
  return (
    <group>
      {Object.entries(slots).map(([key, sl]) => {
        const x = sl.x_mm * MM, z = sl.y_mm * MM
        // 2026-05-01 Phase 4 — concept_area 우선, zone_label fallback
        const conceptColor = sl.concept_area ? CONCEPT_AREA_BORDER_COLORS[sl.concept_area] : null
        const zone = sl.zone_label || "mid_zone"
        const color = conceptColor || ZONE_BORDER_COLORS[zone] || "#94a3b8"
        return (
          <group key={key} position={[x, 0.02, z]}>
            {/* 원형 마커 — ref_point(다이아몬드)와 구분 */}
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <circleGeometry args={[0.06, 16]} />
              <meshBasicMaterial color={color} transparent opacity={0.7} depthWrite={false} />
            </mesh>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <ringGeometry args={[0.06, 0.085, 16]} />
              <meshBasicMaterial color="#ffffff" transparent opacity={0.6} depthWrite={false} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}

interface ExportOptions {
  includeZones?: boolean        // zone 색 바닥 (entrance/mid/deep) 포함 여부. 기본 false
  includeFloorTexture?: boolean // 바닥 패턴 텍스처 포함 여부. 기본 true (적용된 패턴 그대로 출력)
  filename?: string             // 확장자 제외 파일명. 기본 'popup_layout'. includeZones=true 시 '_zone' suffix 자동 추가
}

function ExportHandler({ exportFnRef }: { exportFnRef: React.MutableRefObject<((opts?: ExportOptions) => void) | null> }) {
  const { scene } = useThree()
  useEffect(() => {
    exportFnRef.current = async (opts?: ExportOptions) => {
      const includeZones = opts?.includeZones ?? false
      const includeFloorTexture = opts?.includeFloorTexture ?? true
      const baseName = opts?.filename?.trim() || 'popup_layout'
      const { GLTFExporter } = await import("three/examples/jsm/exporters/GLTFExporter.js")
      const exporter = new GLTFExporter()

      // 씬을 복사해 clone 에서 제외 노드를 제거 → 원본 씬 건드리지 않음.
      //  .visible 토글 방식은 2개 동시 export (zone 포함+제외) 시 race condition 발생해 편집 화면
      //  고착 문제가 있었음. clone 방식은 원본 씬 영향 0 + 동시 호출 안전.
      //  clone(true) 는 Object3D 트리만 deep copy, geometry/material 은 ref 공유 → 빠름.
      const cloned = scene.clone(true)
      // 구조 이격구역(화장실/기둥/계단): visible 강제 + GLB용 불투명 재질 교체 (뷰어 원본은 반투명 유지)
      // excludeFromGlb 조상을 가진 노드(Text 레이블 등)는 건너뜀 — troika 커스텀 쉐이더는 clone 불가
      const _hasExcludeAncestor = (o: THREE.Object3D): boolean => {
        let cur: THREE.Object3D | null = o.parent
        while (cur) {
          if ((cur.userData as Record<string, unknown>)?.excludeFromGlb) return true
          cur = cur.parent
        }
        return false
      }
      cloned.traverse((o: THREE.Object3D) => {
        if (!(o.userData as Record<string, unknown>)?.isDeadZone) return
        o.visible = true
        o.traverse((child: THREE.Object3D) => {
          if (_hasExcludeAncestor(child)) return
          const mesh = child as THREE.Mesh
          if (!mesh.isMesh || !mesh.material || Array.isArray(mesh.material)) return
          const m = (mesh.material as THREE.MeshStandardMaterial).clone()
          m.opacity = 1.0
          m.transparent = false
          m.depthWrite = true
          mesh.material = m
        })
      })
      const toRemove: THREE.Object3D[] = []
      cloned.traverse((o: THREE.Object3D) => {
        const ud = o.userData as Record<string, unknown>
        const shouldHide = ud?.excludeFromGlb || (ud?.zoneOverlay && !includeZones)
        if (shouldHide) toRemove.push(o)
      })
      toRemove.forEach((o) => o.parent?.remove(o))
      // 바닥 패턴 제외 옵션: floor mesh 의 material 을 단색으로 교체 (clone 에만 적용, 원본 유지)
      if (!includeFloorTexture) {
        cloned.traverse((o: THREE.Object3D) => {
          const ud = o.userData as Record<string, unknown>
          if (ud?.isFloor && (o as THREE.Mesh).isMesh) {
            ;(o as THREE.Mesh).material = new THREE.MeshStandardMaterial({ color: '#f8fafc', roughness: 0.95 })
          }
        })
      }
      debugLog(`[glb-export] stripped ${toRemove.length} from clone (includeZones=${includeZones} includeFloorTexture=${includeFloorTexture})`)

      exporter.parse(cloned, (result) => {
        const blob = new Blob([result as ArrayBuffer], { type: "model/gltf-binary" })
        const url = URL.createObjectURL(blob); const a = document.createElement("a")
        a.href = url
        a.download = includeZones ? `${baseName}_zone.glb` : `${baseName}.glb`
        document.body.appendChild(a); a.click()
        document.body.removeChild(a); URL.revokeObjectURL(url)
        debugLog(`[glb-export] download triggered size=${blob.size} bytes filename=${a.download}`)
      }, (err) => {
        console.error("GLB export failed:", err)
      }, { binary: true, onlyVisible: true })
    }
  }, [scene, exportFnRef])
  return null
}

interface Props {
  spaceData: SpaceData
  layoutObjects: LayoutObject[]
  onUpdateObject?: (id: string, changes: Partial<LayoutObject>) => void
  /** 오브젝트 클릭/빈 공간 클릭 시 호출 — ResultPage 사이드바 선택과 동기화 */
  onObjectSelect?: (index: number | null) => void
  /** 사용자 설치 가벽 — 3D 박스로 렌더 (FloorView2D와 동일 데이터) */
  walls?: Array<{ id: string; x: number; z: number; rotation: number; length: number; height: number; thickness: number }>
  /** 가벽 이동/회전 업데이트 콜백 — editMode=move/rotate 시 walls 드래그·회전 반영 */
  onUpdateWall?: (id: string, changes: Partial<{ x: number; z: number; rotation: number }>) => void
  // ── 팔레트 controlled props (optional; 없으면 내부 state fallback) ──
  editMode?: 'view' | 'move' | 'rotate'
  onEditModeChange?: (m: 'view' | 'move' | 'rotate') => void
  /** 이격구역 type별 가시 Set. undefined면 내부 showDeadZones/showWalls 로직 fallback. */
  visibleDeadZoneTypes?: Set<string>
  arteryMode?: 'arrow' | 'buffer' | 'off'
  onArteryModeChange?: (m: 'arrow' | 'buffer' | 'off') => void
  showRefPoints?: boolean
  showSlots?: boolean
  /** 구역 색상(ZoneFloors) ON/OFF. 미지정 시 true */
  showZoneFloors?: boolean
  /** 개별 zone 가시성 — 지정 시 해당 key 만 렌더. 미지정 시 전체 표시 */
  visibleZoneKeys?: Set<string>
  /** 2026-05-01 Phase 4-2 갈래 3 — concept_area 폴리곤 채우기 ON/OFF (large 전용). 미지정 시 true */
  showConceptAreas?: boolean
  /** 개별 concept area 가시성 — 지정 시 해당 key 만 렌더. 미지정 시 전체 표시 */
  visibleConceptAreaKeys?: Set<string>
  /** concept_area 토글 핸들러 — 툴바 버튼용 */
  onToggleConceptAreas?: () => void
  /** 바닥 버튼 팝오버용 컨셉구역 정의 목록 */
  conceptAreaDefs?: { key: string; label: string; color: string }[]
  /** 숨겨진 컨셉구역 key Set (바닥 버튼 팝오버 ON/OFF 표시용) */
  hiddenConceptAreaKeys?: Set<string>
  /** 개별 컨셉구역 토글 콜백 */
  onToggleConceptArea?: (key: string) => void
  /** 전체 컨셉구역 ON/OFF 토글 콜백 */
  onToggleAllConceptAreas?: () => void
  /** 팔레트 사용 시 내부 상단 툴바 숨김 */
  hideInternalToolbar?: boolean
  /** GLB export 함수를 부모에게 전달 (팔레트에서 버튼 호출용). opts 로 zone/바닥패턴/파일명 조절 */
  onExportReady?: (fn: (opts?: { includeZones?: boolean; includeFloorTexture?: boolean; filename?: string }) => void) => void
  /** 배치 후 ref_point/slot 상태 — 4개 독립 토글로 가시화 */
  refPointStatus?: Array<{ id: string; coord: [number, number]; zone_label?: string; type?: 'ref_point' | 'slot'; size_mm?: number; status: 'success' | 'rejected' | 'untried'; placed_obj?: string; rejects?: any[] }>
  /** 팔레트 토글 버튼 핸들러 — ViewerActionButtons 첫 번째 버튼으로 노출 */
  onTogglePalette?: () => void
  /** 팔레트 현재 열림 여부 — 버튼 활성 스타일 표시용 */
  paletteActive?: boolean
  /** [DEV] Python 파이프라인 GLB 다운로드 버튼 핸들러. 미지정 시 버튼 숨김 */
  onDownloadPythonGlb?: () => void
  /** 프로젝트 이름 — `.glb` 팝오버 파일명 input 기본값. 미지정 시 'popup_layout' */
  projectName?: string | null
  /** 부동선(sub_path) 좌표.
   *  형식 변경 (2026-05-04) - 단일 라인 number[][] (옛) -> 여러 라인 number[][][] (신, 가지 형태).
   *  각 가지 = 별 라인. main_artery 에서 좁은 영역 / 고립 ref_point 까지 일자 동선.
   *  빈 list / undefined -> 미표시. */
  subPath?: number[][][]
  /** 부동선 가시성 toggle (controlled). 미지정 시 내부 state(true) fallback. */
  subPathVisible?: boolean
  onSubPathVisibleChange?: (v: boolean) => void
  /** 주동선(main_artery) 좌표 [[x_mm, y_mm], ...] (2026-05-04 신설).
   *  변경 전엔 spaceData.main_artery 였으나 walk_mm 이 place 단계로 이동되며 placeResult.main_artery 로 받음.
   *  순환 동선 (loop spine) 또는 일자 fallback. 빈 list / undefined / null → spaceData.main_artery fallback. */
  mainArtery?: number[][] | null
}

export default function Viewer3D({
  spaceData, layoutObjects, onUpdateObject, onObjectSelect,
  walls, onUpdateWall,
  editMode: editModeProp, onEditModeChange,
  visibleDeadZoneTypes,
  arteryMode: arteryModeProp, onArteryModeChange,
  showRefPoints: showRefPointsProp,
  showSlots: showSlotsProp,
  showZoneFloors: showZoneFloorsProp,
  visibleZoneKeys,
  showConceptAreas: showConceptAreasProp,
  visibleConceptAreaKeys,
  onToggleConceptAreas,
  conceptAreaDefs,
  hiddenConceptAreaKeys,
  onToggleConceptArea,
  onToggleAllConceptAreas,
  hideInternalToolbar,
  onExportReady,
  refPointStatus,
  onTogglePalette,
  paletteActive,
  onDownloadPythonGlb,
  projectName,
  subPath,
  subPathVisible: subPathVisibleProp,
  onSubPathVisibleChange,
  mainArtery,
}: Props) {
  const exportFnRef = useRef<((opts?: ExportOptions) => void) | null>(null)
  const EQUIPMENT_TYPES = new Set(["sprinkler", "fire_hydrant", "electrical_panel", "emergency_exit", "inner_wall"])
  const STRUCTURAL_TYPES = new Set(["core", "toilet", "stair", "pillar", "core_access", "unknown"])
  const hasDeadZones = (spaceData?.dead_zones ?? []).some(dz => EQUIPMENT_TYPES.has(dz.type))
  const hasWalls = (spaceData?.dead_zones ?? []).some(dz => STRUCTURAL_TYPES.has(dz.type))
  // 2026-05-07 fix — main_artery 가 walk_mm 이동(5/4)으로 placement_result 에서 옴.
  // mainArtery prop (placementResult.main_artery) 우선, fallback 으로 spaceData.main_artery (옛 floor_main_artery 테이블 — 5/4 이후 비어있음).
  // line 1062 의 MainArteryLine fallback 로직과 일관.
  const arteryCoordsForCheck = (mainArtery as any) ?? (spaceData as any)?.main_artery
  const hasArtery = (arteryCoordsForCheck?.length ?? 0) >= 2
  const hasSubPath = (subPath?.length ?? 0) >= 1
  const [showDeadZones, setShowDeadZones] = useState(() => hasDeadZones)
  const [showWalls, setShowWalls] = useState(() => hasWalls)
  const [arteryModeInternal, setArteryModeInternal] = useState<'arrow' | 'buffer' | 'off'>(() => hasArtery ? 'arrow' : 'off')
  const [subPathVisibleInternal, setSubPathVisibleInternal] = useState<boolean>(() => hasSubPath)
  const [floorTextureKey, setFloorTextureKey] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // collisionIds: 객체가 dead_zone 과 겹치면 Set 에 추가 → PlacedObject 가 빨강 표시
  // (TR_D 4-27 [데드존_빨강표시_사라짐] fix — 4-28)
  const [collisionIds, setCollisionIds] = useState<Set<string>>(new Set())

  // 객체 ↔ dead_zone collision 검사 (객체 위치/dead_zones 변경마다 재계산)
  useEffect(() => {
    const next = new Set<string>()
    const dzs = spaceData?.dead_zones ?? []
    for (const obj of layoutObjects) {
      for (const dz of dzs) {
        if (objectHitsDeadZone(obj, dz)) {
          next.add(obj.id)
          break
        }
      }
    }
    // 변화 없으면 setState skip (불필요 re-render 방지)
    if (next.size === collisionIds.size && [...next].every(id => collisionIds.has(id))) return
    setCollisionIds(next)
    // collisionIds 자체는 dep 에서 제외 (re-render 무한 루프 방지)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutObjects, spaceData?.dead_zones])
  const [editModeInternal, setEditModeInternal] = useState<'view' | 'move' | 'rotate'>('view')
  const [draggingObj, setDraggingObj] = useState<{ id: string; offsetX: number; offsetZ: number } | null>(null)
  const rotatingObj = useRef<{ id: string; startX: number; startAngle: number } | null>(null)
  // 가벽 드래그/회전 상태 (editMode 공유)
  const [draggingWall, setDraggingWall] = useState<{ id: string; offsetX: number; offsetZ: number } | null>(null)
  const rotatingWall = useRef<{ id: string; startX: number; startAngle: number } | null>(null)

  // controlled/uncontrolled fallback
  const editMode = editModeProp ?? editModeInternal
  const setEditMode = (m: 'view' | 'move' | 'rotate') => {
    if (onEditModeChange) onEditModeChange(m)
    else setEditModeInternal(m)
  }
  const arteryMode = arteryModeProp ?? arteryModeInternal
  const setArteryMode = (updater: (prev: 'arrow' | 'buffer' | 'off') => 'arrow' | 'buffer' | 'off') => {
    const next = updater(arteryMode)
    if (onArteryModeChange) onArteryModeChange(next)
    else setArteryModeInternal(next)
  }
  const subPathVisible = subPathVisibleProp ?? subPathVisibleInternal
  const setSubPathVisible = (v: boolean | ((prev: boolean) => boolean)) => {
    const next = typeof v === 'function' ? (v as (prev: boolean) => boolean)(subPathVisible) : v
    if (onSubPathVisibleChange) onSubPathVisibleChange(next)
    else setSubPathVisibleInternal(next)
  }
  // 기본값: prop 없으면 ref_point는 보이고 slots는 숨김 (기존 동작 유지)
  const showRefPoints = showRefPointsProp ?? true
  const showSlots = showSlotsProp ?? false
  // 2026-05-01 Phase 4-2 갈래 3 — concept_area 폴리곤 default ON (large 컨셉영역 색칠 + 라벨)
  const showZoneFloors = showZoneFloorsProp ?? true
  const showConceptAreas = showConceptAreasProp ?? true

  // GLB export 함수를 부모에게 전달
  useEffect(() => {
    if (onExportReady) {
      // onExportReady — 외부 팔레트(ResultPage) 로 export 함수 전달. opts 그대로 forward.
      onExportReady((opts?: { includeZones?: boolean; filename?: string }) => exportFnRef.current?.(opts))
    }
  }, [onExportReady])

  useEffect(() => {
    const onUp = () => {
      if (draggingObj) setDraggingObj(null)
      if (draggingWall) setDraggingWall(null)
      rotatingObj.current = null
      rotatingWall.current = null
    }
    const onMove = (e: PointerEvent) => {
      const r = rotatingObj.current
      if (r && onUpdateObject) {
        const dx = e.clientX - r.startX
        const newAngle = Math.round(r.startAngle + dx * 0.5) % 360
        onUpdateObject(r.id, { rotation_deg: newAngle < 0 ? newAngle + 360 : newAngle })
      }
      const rw = rotatingWall.current
      if (rw && onUpdateWall) {
        const dx = e.clientX - rw.startX
        const newAngle = Math.round(rw.startAngle + dx * 0.5) % 360
        onUpdateWall(rw.id, { rotation: newAngle < 0 ? newAngle + 360 : newAngle })
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'q' || e.key === 'Q') setEditMode('view')
      else if (e.key === 'w' || e.key === 'W') setEditMode('move')
      else if (e.key === 'e' || e.key === 'E') setEditMode('rotate')
    }
    window.addEventListener("pointerup", onUp)
    window.addEventListener("pointermove", onMove)
    window.addEventListener("keydown", onKey)
    return () => { window.removeEventListener("pointerup", onUp); window.removeEventListener("pointermove", onMove); window.removeEventListener("keydown", onKey) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draggingObj, draggingWall, onUpdateObject, onUpdateWall])

  const handleDragMove = (worldX: number, worldZ: number) => {
    if (draggingObj && onUpdateObject) {
      const obj = layoutObjects.find(o => o.id === draggingObj.id)
      if (obj) {
        const w = obj.width_mm * MM, d = obj.depth_mm * MM
        onUpdateObject(obj.id, {
          center_x_mm: Math.round((worldX - draggingObj.offsetX - w / 2) / MM),
          center_y_mm: Math.round((worldZ - draggingObj.offsetZ - d / 2) / MM),
        })
      }
    }
    if (draggingWall && onUpdateWall) {
      onUpdateWall(draggingWall.id, {
        x: Math.round((worldX - draggingWall.offsetX) / MM),
        z: Math.round((worldZ - draggingWall.offsetZ) / MM),
      })
    }
  }

  const { cx, cz, size } = useMemo(() => {
    const poly = spaceData?.floor?.polygon_mm ?? [];
    if (poly.length === 0) return { cx: 0, cz: 0, size: 10 };
    const xs = poly.map(p => p[0]); const ys = poly.map(p => p[1])
    return { cx: ((Math.min(...xs) + Math.max(...xs)) / 2) * MM, cz: ((Math.min(...ys) + Math.max(...ys)) / 2) * MM, size: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * MM }
  }, [spaceData])

  if (!spaceData?.floor?.polygon_mm?.length) {
    return <div className="w-full h-full flex items-center justify-center text-slate-500">3D 데이터 로딩 중...</div>
  }

  // 카메라: 0,0 기준 정면 위에서 내려다봄 (Y-up, Z+ 방향이 정면)
  const cameraPos: [number, number, number] = [cx, size * 1.5, cz + size * 0.8]

  return (
    <div className="w-full h-full flex flex-col gap-2">
      {!hideInternalToolbar && (
        <div className="flex items-center justify-between gap-2 flex-wrap px-1 py-1">
          {/* 좌: 편집 모드 */}
          <div className="flex gap-0.5 bg-slate-100 rounded-lg p-0.5 border border-slate-200 shrink-0">
            {([
              { mode: 'view' as const, label: '보기', key: 'Q' },
              { mode: 'move' as const, label: '이동', key: 'W' },
              { mode: 'rotate' as const, label: '회전', key: 'E' },
            ]).map(({ mode, label, key }) => (
              <button key={mode} onClick={() => setEditMode(mode)}
                className={`px-3 py-1.5 text-xs rounded-md font-bold transition-all ${editMode === mode ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}>
                {label} <span className="text-[9px] opacity-50 ml-0.5">{key}</span>
              </button>
            ))}
          </div>
          {/* 우: 기능 버튼 */}
          <div className="shrink-0 ml-auto flex">
            <ViewerActionButtons
              onTogglePalette={onTogglePalette}
              paletteActive={paletteActive}
              showDeadZones={showDeadZones}
              setShowDeadZones={setShowDeadZones}
              hasDeadZones={hasDeadZones}
              showWalls={showWalls}
              setShowWalls={setShowWalls}
              hasWalls={hasWalls}
              arteryMode={arteryMode}
              setArteryMode={setArteryMode}
              hasArtery={hasArtery}
              subPathVisible={subPathVisible}
              setSubPathVisible={setSubPathVisible}
              hasSubPath={hasSubPath}
              floorTextureKey={floorTextureKey}
              setFloorTextureKey={setFloorTextureKey}
              conceptAreaDefs={conceptAreaDefs}
              hiddenConceptAreaKeys={hiddenConceptAreaKeys}
              onToggleConceptArea={onToggleConceptArea}
              onToggleAllConceptAreas={onToggleAllConceptAreas}
            />
          </div>
        </div>
      )}
      <div className="flex-1 rounded-xl overflow-hidden border border-slate-200 bg-white relative">
        <Canvas camera={{ position: cameraPos, fov: 50 }} shadows
          gl={{ antialias: true, toneMapping: THREE.LinearToneMapping, toneMappingExposure: 1.0 }}
          onPointerMissed={() => { debugLog({ event: 'pointer_missed', target: 'canvas_bg' }); setSelectedId(null); onObjectSelect?.(null) }}>
          <color attach="background" args={["#f5f7fa"]} />
          <Suspense fallback={null}>
            {/* 씬 전체 감싸는 group: 바닥/zone/dead zone 등 비-오브젝트 클릭 시 선택 해제.
                PlacedObject는 onClick에서 e.stopPropagation() 하므로 여기까지 버블링 안 됨 */}
            <group onClick={(e) => { debugLog({ event: 'scene_deselect', hit: e.object?.type ?? 'unknown' }); setSelectedId(null); onObjectSelect?.(null) }}>
            <ExportHandler exportFnRef={exportFnRef} />
            <ambientLight intensity={2.2} color="#ffffff" />
            <directionalLight position={[size * 0.8, size * 1.5, size * 0.8]} intensity={0.5} castShadow shadow-mapSize={1024} />
            <directionalLight position={[-size * 0.5, size, -size * 0.5]} intensity={0.25} />
            <FloorShape polygon={spaceData.floor.polygon_mm} textureKey={floorTextureKey} />
            {/* 이하 debug/overlay — GLB export 시 userData.excludeFromGlb 로 자동 제외 */}
            {/* Zone 색 바닥은 별도 zoneOverlay 태그 — export 시 사용자 확인으로 포함/제외 선택 */}
            {showZoneFloors && (
              <group userData={{ zoneOverlay: true }}>
                <ZoneFloors zoneMap={spaceData.zone_map as any} visibleKeys={visibleZoneKeys} />
              </group>
            )}
            {/* 2026-05-01 Phase 4-2 갈래 3 — concept_area 폴리곤 채우기 + 한국어 라벨 (large 전용) */}
            {showConceptAreas && (
              <group userData={{ zoneOverlay: true }}>
                <ConceptAreaFloors areas={spaceData.concept_areas} visibleKeys={visibleConceptAreaKeys} />
              </group>
            )}
            {showRefPoints && (
              <group userData={{ excludeFromGlb: true }}>
                <ReferencePointMarkers refPoints={spaceData.reference_points as any} />
              </group>
            )}
            {/* slots 가시화 (소형·중형 전용 — 데이터 없으면 자동 스킵) */}
            {showSlots && (
              <group userData={{ excludeFromGlb: true }}>
                <SlotMarkers slots={(spaceData as any).slots} />
              </group>
            )}
            {/* 배치 후 ref_point/slot 상태 표시 — 4개 독립 토글 (jinkyu) */}
            <group userData={{ excludeFromGlb: true }}>
            {refPointStatus && refPointStatus.map((rp) => {
              const rpType = rp.type ?? (rp.id.startsWith('wall_') || rp.id.startsWith('iwall_') || rp.id.startsWith('center_') || rp.id.startsWith('placed_') ? 'ref_point' : 'slot')
              const isSuccess = rp.status === 'success'
              const isRejected = rp.status === 'rejected'
              if (rp.status === 'untried') return null
              return null
              const x = rp.coord[0] * MM, z = rp.coord[1] * MM
              const color = isSuccess ? '#10b981' : '#ef4444'
              const radiusMm = rp.size_mm ?? (rpType === 'ref_point' ? 2000 : 250)
              const outer = radiusMm * MM
              if (rpType === 'slot') {
                return (
                  <group key={`rpstatus-${rp.id}`} position={[x, 0.03, z]}>
                    <mesh rotation={[-Math.PI / 2, 0, 0]}>
                      <circleGeometry args={[outer, 32]} />
                      <meshBasicMaterial color={color} transparent opacity={0.6} depthWrite={false} />
                    </mesh>
                  </group>
                )
              }
              const thickness = Math.max(outer * 0.15, 0.04)
              const inner = outer - thickness
              return (
                <group key={`rpstatus-${rp.id}`} position={[x, 0.03, z]}>
                  <mesh rotation={[-Math.PI / 2, 0, 0]}>
                    <ringGeometry args={[inner, outer, 48]} />
                    <meshBasicMaterial color={color} transparent opacity={0.35} depthWrite={false} />
                  </mesh>
                </group>
              )
            })}
            </group>
            {/* 사용자 설치 가벽 — 3D 박스 렌더 + 이동/회전 인터랙션 (editMode에 따라) */}
            {walls && walls.map(w => {
              const x = w.x * MM, z = w.z * MM
              const len = w.length * MM, th = w.thickness * MM, h = w.height * MM
              const rad = (w.rotation * Math.PI) / 180
              const isDragging = draggingWall?.id === w.id
              const isRotating = rotatingWall.current?.id === w.id
              const active = isDragging || isRotating
              return (
                <group
                  key={w.id}
                  position={[x, h / 2, z]}
                  rotation={[0, -rad, 0]}
                  onPointerDown={(e) => {
                    if (!onUpdateWall) return
                    if (e.nativeEvent.ctrlKey) return
                    e.stopPropagation()
                    if (editMode === 'rotate') {
                      rotatingWall.current = { id: w.id, startX: e.nativeEvent.clientX, startAngle: w.rotation }
                      return
                    }
                    if (editMode === 'move') {
                      setDraggingWall({ id: w.id, offsetX: e.point.x - x, offsetZ: e.point.z - z })
                    }
                  }}
                >
                  <mesh castShadow receiveShadow>
                    <boxGeometry args={[len, h, th]} />
                    <meshStandardMaterial color={active ? '#fbbf24' : '#e2e8f0'} roughness={0.85} />
                  </mesh>
                </group>
              )
            })}
            <group userData={{ excludeFromGlb: true }}>
              <MainArteryLine coords={mainArtery ?? (spaceData as any).main_artery} mode={arteryMode} />
              {/* 2026-04-29 (#116 F-8 복원): 부동선 — 외곽 복귀 동선 (toggle: 부동선 버튼) */}
              {subPathVisible && <SubPathBranches branches={subPath} />}
            </group>
            {/* 구조 이격구역(화장실/기둥/계단) — 항상 씬에 포함, GLB 내보내기 대상. visible 로 표시만 제어 */}
            <group visible={showWalls} userData={{ isDeadZone: true }}>
              {spaceData.dead_zones
                .filter(dz => !["partition_wall", "partition_wall_I", "partition_wall_L"].includes(dz.type) && STRUCTURAL_TYPES.has(dz.type))
                .map((dz, i) => (
                  <DeadZoneDisk key={`dz-s-${i}-${dz.type}`} center={dz.center_mm} radius={dz.radius_mm} type={dz.type} index={i} polygon={(dz as any).polygon_mm} />
                ))}
            </group>
            {/* 설비 이격구역(소화전/분전반 등) — 화면 표시 전용, GLB 제외 */}
            <group userData={{ excludeFromGlb: true }}>
              {showDeadZones && spaceData.dead_zones
                .filter(dz => !["partition_wall", "partition_wall_I", "partition_wall_L"].includes(dz.type) && EQUIPMENT_TYPES.has(dz.type))
                .map((dz, i) => (
                  <DeadZoneDisk key={`dz-e-${i}-${dz.type}`} center={dz.center_mm} radius={dz.radius_mm} type={dz.type} index={i} polygon={(dz as any).polygon_mm} />
                ))}
            </group>
            {/* 스프링클러 위치 마커 — 천장 고정 설비 */}
            <group userData={{ excludeFromGlb: true }}>
            {(spaceData as any).sprinklers_mm?.map((sp: number[], i: number) => (
              <group key={`sp-${i}`} position={[sp[0] * MM, 0.02, sp[1] * MM]}>
                <mesh rotation={[-Math.PI / 2, 0, 0]}>
                  <ringGeometry args={[0.08, 0.15, 24]} />
                  <meshBasicMaterial color="#3b82f6" transparent opacity={0.8} depthWrite={false} />
                </mesh>
                <mesh rotation={[-Math.PI / 2, 0, 0]}>
                  <circleGeometry args={[0.06, 12]} />
                  <meshBasicMaterial color="#3b82f6" transparent opacity={0.4} depthWrite={false} />
                </mesh>
                <Text position={[0, 0.25, 0]} fontSize={0.12} color="#2563eb" anchorX="center" outlineWidth={0.01} outlineColor="#ffffff">SP#{i + 1}</Text>
              </group>
            ))}
            {/* 소화전 위치 마커 */}
            {(spaceData as any).hydrants_mm?.map((h: number[], i: number) => (
              <group key={`fh-${i}`} position={[h[0] * MM, 0.02, h[1] * MM]}>
                <mesh rotation={[-Math.PI / 2, 0, 0]}>
                  <planeGeometry args={[0.25, 0.25]} />
                  <meshBasicMaterial color="#f97316" transparent opacity={0.6} depthWrite={false} />
                </mesh>
                <Text position={[0, 0.25, 0]} fontSize={0.12} color="#ea580c" anchorX="center" outlineWidth={0.01} outlineColor="#ffffff">FH#{i + 1}</Text>
              </group>
            ))}
            {/* 분전반 위치 마커 */}
            {(spaceData as any).electric_panels_mm?.map((ep: number[], i: number) => (
              <group key={`ep-${i}`} position={[ep[0] * MM, 0.02, ep[1] * MM]}>
                <mesh rotation={[-Math.PI / 2, 0, 0]}>
                  <planeGeometry args={[0.2, 0.2]} />
                  <meshBasicMaterial color="#a855f7" transparent opacity={0.6} depthWrite={false} />
                </mesh>
                <Text position={[0, 0.25, 0]} fontSize={0.12} color="#9333ea" anchorX="center" outlineWidth={0.01} outlineColor="#ffffff">EP#{i + 1}</Text>
              </group>
            ))}
            </group>
            {draggingObj && (
              <group userData={{ excludeFromGlb: true }}>
                <FloorDragPlane onDragMove={handleDragMove} />
              </group>
            )}
            {layoutObjects.map((obj, i) => (
              <PlacedObject key={obj.id} obj={obj} selected={obj.id === selectedId} hasCollision={collisionIds.has(obj.id)}
                onClick={() => { debugLog({ event: 'object_select', type: obj.object_type, id: obj.id, index: i }); setSelectedId(obj.id); onObjectSelect?.(i) }}
                onResize={editMode === 'move' ? onUpdateObject : undefined}
                onStartDrag={editMode === 'move' ? (id, ox, oz) => setDraggingObj({ id, offsetX: ox, offsetZ: oz }) : undefined}
                onStartRotate={editMode === 'rotate' ? (id, clientX, currentAngle) => {
                  rotatingObj.current = { id, startX: clientX, startAngle: currentAngle }
                } : undefined} />
            ))}
            <group userData={{ excludeFromGlb: true }}>
              <EntranceMarker x={spaceData.entrance?.x_mm || 0} y={spaceData.entrance?.y_mm || 0}
                x2={(spaceData.entrance as any)?.x2_mm} y2={(spaceData.entrance as any)?.y2_mm}
                pointsMm={(spaceData.entrance as any)?.points_mm} confidence={(spaceData.entrance as any)?.confidence} />
            </group>
            {/* drei <Grid> — GLB export 시 shader/rotation 소실로 거대 흰 평면 오염 원인.
                userData 로 반드시 제외. */}
            <group userData={{ excludeFromGlb: true }}>
              <Grid position={[cx, 0.001, cz]} args={[size * 2, size * 2]}
                cellSize={0.5} cellThickness={0.5} cellColor="#cbd5e1"
                sectionSize={2.5} sectionThickness={1.0} sectionColor="#94a3b8"
                fadeDistance={size * 5} fadeStrength={1.2} />
            </group>
            <OrbitControls target={[cx, 0, cz]}
              enablePan enableZoom enableRotate={editMode === 'view'}
              minPolarAngle={0.05} maxPolarAngle={Math.PI / 2.1}
              enableDamping dampingFactor={0.1}
              minDistance={1} maxDistance={size * 4} />
            <group userData={{ excludeFromGlb: true }}>
              <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
                <GizmoViewport labelColor="white" axisHeadScale={1} />
              </GizmoHelper>
            </group>
            </group>
          </Suspense>
        </Canvas>
      </div>
    </div>
  )
}
