package com.landup.file;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

/**
 * 브랜드 매뉴얼 분석 결과 관리.
 *
 * 변경 이력:
 *   - 기존 PlacementDbService.saveBrandAnalysis + updateBrandAnalysisStatus 흡수
 *   - brand_analyses → brand_manuals (테이블명 변경)
 *   - space_data_json → brand_data_json
 *   - updateBrandAnalysisStatus → applyBrandResult
 *   - 2026-04-27 박물관 모델 분리: 원본 저장 책임을 BrandArchiveService 로 이전
 *     이 서비스는 분석 결과 (brand_data_json) 만 책임. 원본 파일은 brand_archive 테이블
 *
 * 흐름: 사용자 매뉴얼 업로드
 *   → BrandArchiveService.saveArchive() — 원본 박물관 INSERT
 *   → BrandManualService.saveBrandManual() — 분석 stub INSERT (brand_archive_id 가리킴)
 *   → Python brand worker 분석
 *   → applyBrandResult — brand_data_json UPDATE
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BrandManualService {

    private final BrandManualRepository repo;
    private final BrandArchiveService brandArchiveService;
    private final ObjectMapper objectMapper;

    // ══════════════ 업로드 ══════════════

    /**
     * 매뉴얼 업로드 → 원본 (BrandArchive) + 분석 stub (BrandManual) 동시 INSERT.
     *
     * @return 생성된 BrandManual id (분석 결과 trail)
     */
    @Transactional
    public Long saveBrandManual(Long userId, MultipartFile file) {
        Long archiveId = brandArchiveService.saveArchive(userId, file);
        BrandManual record = BrandManual.builder()
                .userId(userId)
                .brandArchiveId(archiveId)
                .pageCount(0)
                .status(BrandManual.ManualStatus.processing)
                .build();
        return repo.save(record).getId();
    }

    // ══════════════ brand worker 결과 반영 ══════════════

    /**
     * brand done → brand_data_json UPDATE + status.
     */
    @Transactional
    public void applyBrandResult(Long id, BrandManual.ManualStatus status, Map<String, Object> result) {
        repo.findById(id).ifPresent(record -> {
            record.setStatus(status);
            try {
                record.setBrandDataJson(objectMapper.writeValueAsString(result));
            } catch (Exception e) {
                log.warn("[DB] brand_manuals brand_data_json 저장 실패: {}", e.getMessage());
            }
        });
    }

    @Transactional
    public void markError(Long id, String errorMessage) {
        repo.findById(id).ifPresent(record -> {
            record.setStatus(BrandManual.ManualStatus.error);
            if (errorMessage != null) record.setErrorMessage(errorMessage);
        });
    }

    // ══════════════ 조회 ══════════════

    public BrandManual getOrThrow(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "brand_manual not found: " + id));
    }

    public List<BrandManual> listByUser(Long userId) {
        return repo.findAllByUserIdOrderByCreatedAtDesc(userId);
    }
}
