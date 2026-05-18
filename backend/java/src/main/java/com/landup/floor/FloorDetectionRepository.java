package com.landup.floor;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 신 스키마 변환:
 *   findByPdfPageId → findAllByPdfIdOrderByPageNumberAsc → findAllByFloorArchiveIdOrderByPageNumberAsc (2026-04-27)
 *   findAllByPdfIdAndPageNumber → findAllByFloorArchiveIdAndPageNumber (2026-04-27)
 *   findTopByOrderByIdDesc 유지 (getLatestFloorDetectionId 용)
 */
public interface FloorDetectionRepository extends JpaRepository<FloorDetection, Long> {
    List<FloorDetection> findAllByFloorArchiveIdOrderByPageNumberAsc(Long floorArchiveId);
    List<FloorDetection> findAllByFloorArchiveIdAndPageNumber(Long floorArchiveId, Integer pageNumber);
    List<FloorDetection> findAllByScaleTypeAndStatus(FloorDetection.ScaleType scaleType,
                                                     FloorDetection.DetectionStatus status);
    Optional<FloorDetection> findTopByOrderByIdDesc();

    /**
     * 분석 자산 retention cron 용 — created_at + 30일 경과 + user_project 참조 0.
     * 자식 row (placement_results / placement_objects / floor_anchors 등) 는
     * ON DELETE CASCADE 자동 정리.
     */
    @Modifying
    @Query("DELETE FROM FloorDetection fd " +
           "WHERE fd.createdAt < :cutoff " +
           "AND NOT EXISTS (SELECT 1 FROM UserProject up WHERE up.floorDetectionId = fd.id)")
    int deleteOrphanedOlderThan(@Param("cutoff") LocalDateTime cutoff);
}
