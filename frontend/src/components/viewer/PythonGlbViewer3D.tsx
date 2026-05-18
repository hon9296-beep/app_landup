/**
 * PythonGlbViewer3D — Python 파이프라인이 생성·저장한 GLB 를 서버에서 받아 Three.js 씬으로 렌더.
 *
 * 용도: 편집 전 "공식 배치 결과 원본" 프리뷰. 편집 불가 (read-only, OrbitControls 만).
 *
 * 플로우:
 *   1. axiosClient (JWT 자동 첨부) 로 GET /api/placements/results/{id}/glb
 *   2. 응답 blob → URL.createObjectURL → useGLTF 로드
 *   3. 컴포넌트 unmount 시 objectURL revoke + useGLTF 캐시 evict → 메모리 누수·잔상 차단
 *
 * "오염 차단": 모드 전환(3D/2D/GLB) 시 React 가 mount/unmount 를 자동 처리하고,
 * useEffect cleanup 에서 blob URL 을 명시적으로 해제한다.
 */
import { Canvas } from '@react-three/fiber';
import { OrbitControls, useGLTF } from '@react-three/drei';
import { Suspense, useEffect, useState } from 'react';
import axiosClient from '../../lib/axiosClient';
import { debugLog } from '../../lib/debug';

interface Props {
  placementResultId: number;
}

function GlbScene({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  return <primitive object={scene} />;
}

export default function PythonGlbViewer3D({ placementResultId }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let localUrl: string | null = null;
    setLoading(true);
    setError(null);
    setBlobUrl(null);

    debugLog(`[glb-view] 로드 시작 placement_result_id=${placementResultId}`);
    axiosClient
      .get<Blob>(`/placements/results/${placementResultId}/glb`, { responseType: 'blob' })
      .then((res) => {
        if (cancelled) return;
        localUrl = URL.createObjectURL(res.data);
        debugLog(
          `[glb-view] blob 수신 size=${res.data.size} bytes contentType=${res.headers['content-type']}`,
        );
        setBlobUrl(localUrl);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const e = err as { response?: { status?: number }; message?: string };
        const msg = e?.response?.status ? `HTTP ${e.response.status}` : e?.message ?? 'load failed';
        console.warn(`[glb-view] 로드 실패 ${msg}`);
        setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      if (localUrl) {
        // useGLTF 캐시에서 이 URL 기준 씬 제거 (다음 진입에 새 로드 보장)
        try { useGLTF.clear(localUrl); } catch { /* drei 내부 상태 이슈 무시 */ }
        URL.revokeObjectURL(localUrl);
        debugLog(`[glb-view] unmount cleanup — blob URL revoked`);
      }
    };
  }, [placementResultId]);

  // 3D/2D 뷰와 동일한 flex 계층 유지 — 부모 <main flex-1 flex overflow-hidden> 의 자식으로서
  //  flex-1 flex flex-col 로 영역 채우고 내부에 Canvas 가 전체 차지. 추가 border/rounded 없음.
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400 text-sm bg-[#070d1a]">
        Python GLB 로딩 중...
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 text-slate-400 text-sm bg-[#070d1a]">
        <div>GLB 생성 결과 없음</div>
        <div className="text-xs text-slate-500">
          배치를 한 번 실행한 뒤 다시 시도해주세요.
        </div>
        <div className="text-[10px] text-slate-600 mt-1">[{error}]</div>
      </div>
    );
  }
  if (!blobUrl) return null;

  return (
    <div className="flex-1 flex flex-col bg-[#070d1a]">
      <div className="w-full h-full">
        <Canvas camera={{ position: [8, 6, 8], fov: 50 }}>
          <color attach="background" args={['#f5f7fa']} />
          <ambientLight intensity={1.8} />
          <directionalLight position={[10, 15, 10]} intensity={0.7} />
          <directionalLight position={[-5, 10, -5]} intensity={0.3} />
          <Suspense fallback={null}>
            <GlbScene url={blobUrl} />
          </Suspense>
          <OrbitControls enablePan enableZoom enableRotate dampingFactor={0.1} enableDamping />
        </Canvas>
      </div>
    </div>
  );
}
