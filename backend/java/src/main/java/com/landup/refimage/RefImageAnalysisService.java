package com.landup.refimage;

import com.landup.refimage.dto.RefImageAnalysisCreateRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * ref_image_analyses 비즈니스 로직.
 *
 * 호출 흐름:
 *   - Python ref_image_analyzer.py → /internal/ref-image-analyses POST → create()
 *   - LLM design 단계에서 풀 fetch → fetchPoolByConceptArea() / fetchPoolByConceptAreaAndBrand()
 *   - 분석 직전 캐시 조회 → findCacheByRefImageId() / findCacheByRefImageIdAndModelVersion()
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RefImageAnalysisService {

    private final RefImageAnalysisRepository repo;

    /** Python 분석 결과 영속 (status=done 으로 저장). */
    @Transactional
    public RefImageAnalysis create(RefImageAnalysisCreateRequest req) {
        RefImageAnalysis entity = RefImageAnalysis.builder()
                .refImageId(req.refImageId())
                .conceptArea(req.conceptArea())
                .brandCategory(req.brandCategory())
                .visionAnalysisJson(req.visionAnalysisJson())
                .modelVersion(req.modelVersion())
                .status(RefImageAnalysis.Status.done)
                .build();
        RefImageAnalysis saved = repo.save(entity);
        log.info("[ref_image_analysis] created id={} ref_image_id={} concept_area={} brand_category={} model={}",
                 saved.getId(), saved.getRefImageId(), saved.getConceptArea(),
                 saved.getBrandCategory(), saved.getModelVersion());
        return saved;
    }

    /** 캐시 조회 — refImageId 기반 (가장 최신). */
    public Optional<RefImageAnalysis> findCacheByRefImageId(Long refImageId) {
        return repo.findTopByRefImageIdOrderByCreatedAtDesc(refImageId);
    }

    /** 캐시 조회 — refImageId + modelVersion 일치 (재분석 회피). */
    public Optional<RefImageAnalysis> findCacheByRefImageIdAndModelVersion(
        Long refImageId, String modelVersion
    ) {
        return repo.findTopByRefImageIdAndModelVersionOrderByCreatedAtDesc(refImageId, modelVersion);
    }

    /** conceptArea 풀 fetch — design 단계 LLM 컨텍스트용. */
    public List<RefImageAnalysis> fetchPoolByConceptArea(String conceptArea) {
        return repo.findByConceptAreaDone(conceptArea);
    }

    /** conceptArea + brandCategory 정밀 풀 fetch (B 옵션). */
    public List<RefImageAnalysis> fetchPoolByConceptAreaAndBrand(
        String conceptArea, String brandCategory
    ) {
        return repo.findByConceptAreaAndBrandCategoryDone(conceptArea, brandCategory);
    }
}
