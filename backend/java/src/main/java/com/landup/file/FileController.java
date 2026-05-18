package com.landup.file;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * 파일 관련 엔드포인트 — 신 스키마 기준.
 *
 * 경로 변경:
 *   GET /pdf-files/{id}/pages     → GET /pdfs/{id}/pages → GET /floor-archives/{id}/pages (2026-04-27)
 *   GET /brand-analyses/{id}      → GET /brand-manuals/{id}
 *
 * 응답 키 변경: pdf_file_id → pdf_id → floor_archive_id (2026-04-27), space_data_json → brand_data_json
 *
 * pdf_pages 테이블 폐기 → floor_archive.pages_json 에서 파싱해 반환.
 */
@RestController
@RequiredArgsConstructor
public class FileController {

    private final FileService fileService;
    private final FloorArchiveRepository floorArchiveRepository;
    private final BrandManualRepository brandManualRepository;
    private final BrandArchiveRepository brandArchiveRepository;
    private final ObjectMapper objectMapper;

    @GetMapping("/users/{userId}/files")
    public Map<String, Object> getUserFiles(
            @PathVariable Long userId,
            @AuthenticationPrincipal User principal
    ) {
        // JWT subject 와 path userId 비교 — 타유저 파일 조회 차단
        if (principal == null || !principal.getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "해당 사용자의 파일에 접근할 수 없습니다.");
        }
        return fileService.getUserFiles(userId);
    }

    /**
     * detect 결과(auto_detected) 조회 — 신 스키마에선 floor_archive.pages_json 에서 첫 페이지 dimensions 추출.
     */
    @GetMapping("/floor-archives/{floorArchiveId}/pages")
    public Map<String, Object> getFloorArchivePages(@PathVariable Long floorArchiveId) {
        FloorArchive archive = floorArchiveRepository.findById(floorArchiveId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "floor_archive not found: " + floorArchiveId));
        Map<String, Object> res = new HashMap<>();
        res.put("floor_archive_id", floorArchiveId);
        res.put("page_count", archive.getPageCount());
        res.put("status", archive.getStatus() != null ? archive.getStatus().name() : null);
        res.put("dimensions", extractFirstPageDimensions(archive.getPagesJson()));
        return res;
    }

    /** brand 결과(brand_data) 조회 — brand_data_json 파싱. */
    @GetMapping("/brand-manuals/{id}")
    public Map<String, Object> getBrandManual(@PathVariable Long id) {
        BrandManual bm = brandManualRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "brand_manual not found: " + id));
        Map<String, Object> res = new HashMap<>();
        res.put("id", bm.getId());
        res.put("user_id", bm.getUserId());
        res.put("status", bm.getStatus() != null ? bm.getStatus().name() : null);
        // 2026-04-27 박물관 모델 분리: pdf_sha256 은 BrandArchive 에서 조회 (7일 retention 후 NULL)
        String sha = null;
        if (bm.getBrandArchiveId() != null) {
            sha = brandArchiveRepository.findById(bm.getBrandArchiveId())
                    .map(BrandArchive::getPdfSha256).orElse(null);
        }
        res.put("pdf_sha256", sha);
        res.put("brand_data", parseJson(bm.getBrandDataJson()));
        return res;
    }

    // ══════════════ 내부 ══════════════

    /**
     * floor_archive.pages_json 에서 첫 페이지 dimensions 추출.
     * 예상 포맷: {"pages": [{"page_number":1, "dimensions":{...}}, ...]} 또는 단일 dict.
     */
    private Map<String, Object> extractFirstPageDimensions(String pagesJson) {
        Map<String, Object> root = parseJson(pagesJson);
        if (root == null) return null;
        Object pages = root.get("pages");
        if (pages instanceof java.util.List<?> list && !list.isEmpty()) {
            Object first = list.get(0);
            if (first instanceof Map<?, ?> pm) {
                @SuppressWarnings("unchecked")
                Map<String, Object> pageMap = (Map<String, Object>) pm;
                Object dims = pageMap.get("dimensions");
                if (dims instanceof Map<?, ?> dm) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> dimMap = (Map<String, Object>) dm;
                    return dimMap;
                }
            }
        }
        return root;
    }

    private Map<String, Object> parseJson(String json) {
        if (json == null || json.isBlank()) return null;
        try {
            return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            return null;
        }
    }
}
