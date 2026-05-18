package com.landup.refimage;

import com.landup.refimage.dto.RefImageAnalysisCreateRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * Python ref_image_analyzer 가 호출하는 internal API.
 *
 * 외부 사용자에게 노출 금지 — /internal/ prefix + 네트워크 레벨 차단 전제.
 * RefImageInternalController 와 동일 패턴 (보안 정책 / 네트워크 분리 동일 적용).
 *
 * 엔드포인트:
 *   POST /internal/ref-image-analyses                  — 분석 결과 1건 등록 (status=done)
 *   GET  /internal/ref-image-analyses/cache?refImageId — 캐시 hit 조회 (refImageId + 선택 modelVersion)
 *   GET  /internal/ref-image-analyses/pool?conceptArea — concept_area 별 풀 fetch (limit + brandCategory 보조)
 */
@RestController
@RequestMapping("/internal/ref-image-analyses")
@RequiredArgsConstructor
public class RefImageAnalysisInternalController {

    private final RefImageAnalysisService service;

    @PostMapping
    public RefImageAnalysis create(@Valid @RequestBody RefImageAnalysisCreateRequest req) {
        return service.create(req);
    }

    /**
     * 캐시 hit 조회.
     * modelVersion 지정 시 → 모델 버전까지 일치하는 분석본 (mismatch 시 빈 응답)
     * modelVersion 미지정 시 → 가장 최신 분석본 1건 (모델 무관)
     */
    @GetMapping("/cache")
    public RefImageAnalysis findCache(
        @RequestParam Long refImageId,
        @RequestParam(required = false) String modelVersion
    ) {
        return (modelVersion == null
                ? service.findCacheByRefImageId(refImageId)
                : service.findCacheByRefImageIdAndModelVersion(refImageId, modelVersion))
                .orElse(null);
    }

    /**
     * concept_area 별 풀 fetch — N+1 흐름의 풀 (Python ref_image_loader 가 design 컨텍스트로 활용).
     * brandCategory 지정 시 정밀 매칭 (B 옵션 — 두 차원 일치 우선).
     * limit 기본 10 (REF_POOL_FETCH_LIMIT 정합).
     */
    @GetMapping("/pool")
    public List<RefImageAnalysis> fetchPool(
        @RequestParam String conceptArea,
        @RequestParam(required = false) String brandCategory,
        @RequestParam(required = false, defaultValue = "10") int limit
    ) {
        List<RefImageAnalysis> pool = (brandCategory == null || brandCategory.isBlank())
                ? service.fetchPoolByConceptArea(conceptArea)
                : service.fetchPoolByConceptAreaAndBrand(conceptArea, brandCategory);
        if (pool.size() > limit) {
            return pool.subList(0, limit);
        }
        return pool;
    }
}
