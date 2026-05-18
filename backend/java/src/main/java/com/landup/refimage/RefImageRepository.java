package com.landup.refimage;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface RefImageRepository extends JpaRepository<RefImage, Long> {

    /**
     * Python 이 DDG 다운로드 전에 호출. sha256 블랙리스트 존재 여부 확인.
     * idx_sha256_black 인덱스로 O(log n) 조회.
     */
    boolean existsByImageSha256AndIsBlacklistedTrue(String imageSha256);

    /** 같은 프로젝트 내 동일 sha256 재등록 감지 (UPDATE 로 처리). */
    Optional<RefImage> findByUserProjectIdAndImageSha256(Long userProjectId, String imageSha256);

    /**
     * sha256 으로 모든 row 조회 — 시스템 자동 blacklist 등록 시 같은 sha256 의 모든
     * user_project row 를 동시에 표시.
     */
    List<RefImage> findAllByImageSha256(String imageSha256);

    /**
     * 관리자 리스트 조회 — 프로젝트 그룹핑 전제, 필터 조합.
     * categoryId / tier / fromDate / toDate 각각 null 가능 (필터 미지정).
     */
    @Query("""
        SELECT r FROM RefImage r
        WHERE r.isDeleted = false
          AND (:categoryId IS NULL OR r.brandCategoryId = :categoryId)
          AND (:tier IS NULL OR r.floorSizeTier = :tier)
          AND (:fromDate IS NULL OR r.createdAt >= :fromDate)
          AND (:toDate IS NULL OR r.createdAt < :toDate)
        ORDER BY r.createdAt DESC
        """)
    Page<RefImage> findForAdmin(
        @Param("categoryId") Long categoryId,
        @Param("tier") RefImage.FloorSizeTier tier,
        @Param("fromDate") LocalDateTime fromDate,
        @Param("toDate") LocalDateTime toDate,
        Pageable pageable
    );

    /** 특정 프로젝트의 ref 이미지 전체 (펼치기 시 카드 그리드 렌더링용). */
    Page<RefImage> findByUserProjectIdAndIsDeletedFalseOrderByCreatedAtDesc(
        Long userProjectId, Pageable pageable
    );
}
