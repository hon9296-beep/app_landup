package com.landup.refimage;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

/**
 * ref_image_analyses Repository.
 *
 * 주요 사용처:
 *   - Python 분석 직전 캐시 조회 (refImageId 기반 hit 확인)
 *   - LLM design 단계에서 풀 fetch (conceptArea 기반 매칭)
 *   - 모델 버전 mismatch 식별 (재분석 큐 후보)
 */
public interface RefImageAnalysisRepository extends JpaRepository<RefImageAnalysis, Long> {

    /** 캐시 hit 조회 — refImageId 기반 분석본 존재 여부 (가장 최신 1건). */
    Optional<RefImageAnalysis> findTopByRefImageIdOrderByCreatedAtDesc(Long refImageId);

    /** 캐시 hit + 모델 버전 일치 — refImageId + modelVersion 매칭. */
    Optional<RefImageAnalysis> findTopByRefImageIdAndModelVersionOrderByCreatedAtDesc(
        Long refImageId, String modelVersion
    );

    /** conceptArea 기반 풀 fetch (status=done). 정렬 / limit 은 호출처에서. */
    @Query("""
        SELECT a FROM RefImageAnalysis a
        WHERE a.conceptArea = :conceptArea
          AND a.status = com.landup.refimage.RefImageAnalysis.Status.done
        ORDER BY a.createdAt DESC
        """)
    List<RefImageAnalysis> findByConceptAreaDone(@Param("conceptArea") String conceptArea);

    /** conceptArea + brandCategory 정밀 매칭 (B 옵션 — 두 차원 일치 우선). */
    @Query("""
        SELECT a FROM RefImageAnalysis a
        WHERE a.conceptArea = :conceptArea
          AND a.brandCategory = :brandCategory
          AND a.status = com.landup.refimage.RefImageAnalysis.Status.done
        ORDER BY a.createdAt DESC
        """)
    List<RefImageAnalysis> findByConceptAreaAndBrandCategoryDone(
        @Param("conceptArea") String conceptArea,
        @Param("brandCategory") String brandCategory
    );

    /** 모델 버전 mismatch 레코드 식별 — 재분석 큐 후보. */
    @Query("""
        SELECT a FROM RefImageAnalysis a
        WHERE a.modelVersion <> :currentVersion
          AND a.status = com.landup.refimage.RefImageAnalysis.Status.done
        """)
    List<RefImageAnalysis> findStaleByModelVersion(@Param("currentVersion") String currentVersion);
}
