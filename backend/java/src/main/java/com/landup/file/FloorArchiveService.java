package com.landup.file;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 도면 원본 박물관 관리 — 2026-04-27 rename (구 PdfService).
 *
 * 변경 이력:
 *   - 기존 PlacementDbService.savePdfFile/updatePdfFileStatus/savePdfPage 흡수
 *   - pdf_files + pdf_pages → pdf 단일 테이블 (pages_json blob)
 *   - savePdfFile       → savePdf
 *   - updatePdfFileStatus + savePdfPage → applyDetectResult
 *   - 2026-04-27: PdfService → FloorArchiveService rename (brand_archive 와 패턴 일관)
 *     savePdf → saveFloorArchive, Pdf → FloorArchive
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FloorArchiveService {

    private final FloorArchiveRepository repo;
    private final S3Service s3Service;
    private final ObjectMapper objectMapper;

    @Value("${file.upload-dir}")
    private String uploadDir;

    // ══════════════ 업로드 ══════════════

    /**
     * 도면 원본 저장 — 로컬 디스크 + S3 둘 다 (2026-04-27 S3 이관).
     *
     * 흐름:
     *   1. 로컬 디스크 저장 (개발 캐시)
     *   2. S3 업로드 (외부 노출 URL + bucket key 받음)
     *   3. DB INSERT (모든 경로 저장)
     *
     * S3 업로드 실패 시 ApiException → 트랜잭션 롤백 (DB INSERT 안 됨).
     */
    @Transactional
    public FloorArchive saveFloorArchive(Long userId, MultipartFile file) {
        String stored = saveFileToDisk(file);
        String s3Key = s3Service.generateKey("floor-archive", userId, file.getOriginalFilename());
        String s3Url = s3Service.upload(file, s3Key);

        FloorArchive record = FloorArchive.builder()
                .userId(userId)
                .originalFilename(file.getOriginalFilename())
                .storedFilename(stored)
                .s3Url(s3Url)
                .s3Key(s3Key)
                .pageCount(0)
                .status(FloorArchive.FloorArchiveStatus.processing)
                .build();
        return repo.save(record);
    }

    // ══════════════ detect worker 결과 반영 ══════════════

    /**
     * detect done → floor_archive.pages_json UPDATE + status=done + page_count 갱신.
     *
     * detectResult 예상 포맷:
     *   {"pages": [{"page_number":1, "dimensions":{...}}, ...]}
     *   또는 단일 dict
     *
     * 분석 결과 본체는 FloorDetection 에 별도 INSERT (auto_detected JSON).
     * 여기서는 페이지 메타 (dimensions) 만 floor_archive.pages_json 에 캐싱.
     */
    @Transactional
    public FloorArchive applyDetectResult(Long floorArchiveId, Map<String, Object> detectResult) {
        FloorArchive archive = getOrThrow(floorArchiveId);
        try {
            archive.setPagesJson(objectMapper.writeValueAsString(detectResult));
        } catch (Exception e) {
            log.warn("[DB] floor_archive.pages_json 직렬화 실패 floorArchiveId={}: {}", floorArchiveId, e.getMessage());
        }
        Object pages = detectResult.get("pages");
        if (pages instanceof List<?> pagesList) {
            archive.setPageCount(pagesList.size());
        } else if (detectResult.containsKey("page_count")) {
            archive.setPageCount(toInt(detectResult.get("page_count"), 0));
        } else {
            archive.setPageCount(1);
        }
        archive.setStatus(FloorArchive.FloorArchiveStatus.done);
        repo.save(archive);
        log.info("[DB] floor_archive UPDATE done (id={}, pageCount={})", floorArchiveId, archive.getPageCount());
        return archive;
    }

    /** detect 실패 시 status=error + error_message 세팅. */
    @Transactional
    public void markError(Long floorArchiveId, String errorMessage) {
        FloorArchive archive = getOrThrow(floorArchiveId);
        archive.setStatus(FloorArchive.FloorArchiveStatus.error);
        if (errorMessage != null) archive.setErrorMessage(errorMessage);
        repo.save(archive);
    }

    // ══════════════ 조회 ══════════════

    public FloorArchive getOrThrow(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "floor_archive not found: " + id));
    }

    public List<FloorArchive> listByUser(Long userId) {
        return repo.findAllByUserIdOrderByCreatedAtDesc(userId);
    }

    // ══════════════ 내부 ══════════════

    private String saveFileToDisk(MultipartFile file) {
        String stored = UUID.randomUUID().toString().replace("-", "") + "_" + file.getOriginalFilename();
        try {
            Path dir = Paths.get(uploadDir);
            if (!Files.exists(dir)) Files.createDirectories(dir);
            Files.write(dir.resolve(stored), file.getBytes());
        } catch (IOException e) {
            log.warn("[파일저장] 실패: {}", e.getMessage());
        }
        return stored;
    }

    private Integer toInt(Object val, Integer fallback) {
        if (val == null) return fallback;
        if (val instanceof Number n) return n.intValue();
        try { return Integer.parseInt(val.toString()); } catch (Exception e) { return fallback; }
    }
}
