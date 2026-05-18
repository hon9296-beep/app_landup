package com.landup.file;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface BrandManualRepository extends JpaRepository<BrandManual, Long> {
    List<BrandManual> findAllByUserIdOrderByCreatedAtDesc(Long userId);

    /**
     * 분석 자산 retention cron 용 — created_at + 30일 경과 + user_project 참조 0.
     * 자식 row (brand_object_specs) 는 ON DELETE CASCADE 자동 정리.
     */
    @Modifying
    @Query("DELETE FROM BrandManual bm " +
           "WHERE bm.createdAt < :cutoff " +
           "AND NOT EXISTS (SELECT 1 FROM UserProject up WHERE up.brandManualId = bm.id)")
    int deleteOrphanedOlderThan(@Param("cutoff") LocalDateTime cutoff);
}
