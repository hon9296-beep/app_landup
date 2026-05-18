/**
 * Python 파이프라인에서 생성 + 저장한 GLB 를 Java 엔드포인트로부터 다운로드하는 클라이언트.
 *
 * 각 단계마다 console 로그 — "어디서 어긋나는지" 추적용.
 *   [glb-client] 요청 시작 url=/placements/results/42/glb
 *   [glb-client] 응답 status=200 contentType=model/gltf-binary
 *   [glb-client] blob 수신 size=7428 bytes type=model/gltf-binary
 *   [glb-client] magic header='glTF' (expected 'glTF') ok=true
 *   [glb-client] 다운로드 완료 filename=landup_python_42.glb
 *
 * Python debug_logs / Java 서버로그 / 브라우저 콘솔 3축 교차로 파이프라인 어느 구간에서
 * 데이터가 끊기는지 즉시 파악 가능.
 */
import axiosClient from './axiosClient';
import { debugLog } from './debug';

export interface GlbDownloadResult {
  ok: boolean;
  sizeBytes?: number;
  filename?: string;
  magicOk?: boolean;
  status?: number;
  error?: string;
}

export async function downloadPythonGlb(placementResultId: number): Promise<GlbDownloadResult> {
  const url = `/placements/results/${placementResultId}/glb`;
  debugLog(`[glb-client] 요청 시작 url=${url} (axiosClient baseURL '/api' prefix 자동)`);

  try {
    const res = await axiosClient.get<Blob>(url, { responseType: 'blob' });
    debugLog(
      `[glb-client] 응답 status=${res.status} contentType=${res.headers['content-type']}`,
    );

    const blob = res.data;
    debugLog(`[glb-client] blob 수신 size=${blob.size} bytes type=${blob.type}`);

    // magic header 검증 (glTF binary 포맷은 'glTF' 로 시작)
    const firstBytes = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
    const magic = new TextDecoder().decode(firstBytes);
    const magicOk = magic === 'glTF';
    debugLog(`[glb-client] magic header='${magic}' (expected 'glTF') ok=${magicOk}`);

    // 브라우저 다운로드 트리거
    const filename = `landup_python_${placementResultId}.glb`;
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(objectUrl);

    debugLog(`[glb-client] 다운로드 완료 filename=${filename}`);
    return {
      ok: true,
      sizeBytes: blob.size,
      filename,
      magicOk,
      status: res.status,
    };
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: unknown }; message?: string };
    const status = err.response?.status;
    const bodyStr =
      err.response?.data instanceof Blob
        ? await err.response.data.text().catch(() => '(unreadable blob)')
        : JSON.stringify(err.response?.data ?? null);
    console.warn(`[glb-client] 실패 status=${status} body=${bodyStr} message=${err.message}`);
    return {
      ok: false,
      status,
      error: err.message ?? 'unknown error',
    };
  }
}
