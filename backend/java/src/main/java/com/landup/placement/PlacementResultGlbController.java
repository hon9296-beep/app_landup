package com.landup.placement;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.io.File;
import java.nio.file.Paths;

/**
 * GLB 파일 스트리밍 컨트롤러.
 *
 * placement_result.glb_path 에 저장된 상대경로(예: 'storage/glb/{uuid}.glb')를
 * application.yml 의 glb.base-dir 설정값과 join 해서 로컬 파일시스템에서 바이너리 스트리밍.
 *
 * 엔드포인트: GET /api/placements/results/{placementResultId}/glb
 *   200 — GLB 바이너리 스트림 (Content-Type: model/gltf-binary)
 *   404 — 결과 없음 / glb_path null / 파일 부재
 *
 * 모든 단계에 INFO 로그 남김 — "어디서 어긋나는지" 추적용.
 * Python debug_logs 와 교차 검증하면 원인 구간 즉시 파악 가능.
 */
@RestController
@RequestMapping("/placements/results")
@RequiredArgsConstructor
@Slf4j
public class PlacementResultGlbController {

    private final PlacementResultRepository repository;

    @Value("${glb.base-dir:../}")
    private String glbBaseDir;

    @GetMapping(value = "/{placementResultId}/glb", produces = "model/gltf-binary")
    public ResponseEntity<FileSystemResource> getGlb(@PathVariable Long placementResultId) {
        log.info("[glb] 요청 수신 placementResultId={}", placementResultId);

        PlacementResult pr = repository.findById(placementResultId).orElseThrow(() -> {
            log.warn("[glb] 404 — placement_result 없음 id={}", placementResultId);
            return new ResponseStatusException(HttpStatus.NOT_FOUND, "placement_result not found");
        });

        String glbPath = pr.getGlbPath();
        log.info("[glb] DB 조회 결과 glb_path='{}' (id={}, status={})",
                glbPath, placementResultId, pr.getStatus());

        if (glbPath == null || glbPath.isBlank()) {
            log.warn("[glb] 404 — glb_path null/empty (Python save 실패 혹은 미실행) id={}", placementResultId);
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "glb_path is null");
        }

        File file = Paths.get(glbBaseDir, glbPath).toFile();
        String abs = file.getAbsolutePath();
        boolean exists = file.exists();
        long size = exists ? file.length() : -1L;
        log.info("[glb] 파일 resolve baseDir='{}' relative='{}' abs='{}' exists={} size={}",
                glbBaseDir, glbPath, abs, exists, size);

        if (!exists || !file.isFile()) {
            log.warn("[glb] 404 — 파일 부재 abs='{}'", abs);
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "glb file not found on disk: " + abs);
        }

        log.info("[glb] 200 스트리밍 시작 id={} size={} bytes path='{}'",
                placementResultId, size, abs);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType("model/gltf-binary"))
                .contentLength(size)
                .body(new FileSystemResource(file));
    }
}
