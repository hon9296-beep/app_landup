package com.landup.file;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 사용자 파일 목록 조회 — 신 스키마 기준.
 *
 * 변환 이력:
 *   - PdfFileRepository → PdfRepository → FloorArchiveRepository (2026-04-27)
 *   - BrandAnalysisRepository → BrandManualRepository
 *   - 응답 내부 필드는 신 Entity 기준 (id/original_filename/page_count/status/created_at)
 *   - 2026-04-27 박물관 모델 분리:
 *     · pdf → floor_archive 로 rename (도면 원본 박물관)
 *     · BrandManual 의 originalFilename 컬럼 제거 → BrandArchive 에서 조회
 *     · 박물관 7일 후 archive 사라지면 NULL → "[원본 만료]" 로 표기
 *
 * 프론트 호환 — 응답 최상위 key 변경: pdf_files → floor_archive_files (2026-04-27).
 */
@Service
@RequiredArgsConstructor
public class FileService {

    private final FloorArchiveRepository floorArchiveRepository;
    private final BrandManualRepository brandManualRepository;
    private final BrandArchiveRepository brandArchiveRepository;

    public Map<String, Object> getUserFiles(Long userId) {
        List<FloorArchive> archives = floorArchiveRepository.findAllByUserIdOrderByCreatedAtDesc(userId);
        List<BrandManual> brands = brandManualRepository.findAllByUserIdOrderByCreatedAtDesc(userId);

        // brand_archive 일괄 조회 (N+1 회피)
        List<Long> archiveIds = brands.stream()
                .map(BrandManual::getBrandArchiveId)
                .filter(Objects::nonNull)
                .distinct()
                .toList();
        Map<Long, String> archiveNameMap = archiveIds.isEmpty()
                ? Map.of()
                : brandArchiveRepository.findAllById(archiveIds).stream()
                    .collect(Collectors.toMap(BrandArchive::getId, BrandArchive::getOriginalFilename));

        return Map.of(
                "floor_archive_files", archives.stream().map(f -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("id", f.getId());
                    m.put("original_filename", f.getOriginalFilename());
                    m.put("page_count", f.getPageCount());
                    m.put("status", f.getStatus().name());
                    m.put("created_at", f.getCreatedAt().toString());
                    return m;
                }).toList(),
                "brand_files", brands.stream().map(f -> {
                    Map<String, Object> m = new HashMap<>();
                    m.put("id", f.getId());
                    // brand_archive 7일 retention 으로 archive 사라졌으면 fallback 표기
                    String origFn = f.getBrandArchiveId() != null
                            ? archiveNameMap.getOrDefault(f.getBrandArchiveId(), "[원본 만료]")
                            : "[원본 없음]";
                    m.put("original_filename", origFn);
                    m.put("page_count", f.getPageCount());
                    m.put("status", f.getStatus().name());
                    m.put("created_at", f.getCreatedAt().toString());
                    return m;
                }).toList()
        );
    }
}
