package com.landup.project;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

public interface UserProjectRepository extends JpaRepository<UserProject, Long> {
    List<UserProject> findAllByUserIdOrderByCreatedAtDesc(Long userId);
    Optional<UserProject> findByFloorDetectionId(Long floorDetectionId);
    List<UserProject> findAllByUserIdAndStatus(Long userId, UserProject.ProjectState status);

    // 이번 달 생성한 프로젝트 중 완료됐거나 완료 후 삭제된 것 카운트 (플랜 한도 계산)
    @Query("SELECT COUNT(p) FROM UserProject p WHERE p.userId = :userId " +
           "AND p.createdAt >= :from AND p.createdAt < :to " +
           "AND (p.status = 'done' OR (p.deletedAt IS NOT NULL AND p.wasDone = TRUE))")
    int countThisMonthProjects(@Param("userId") Long userId,
                               @Param("from")   LocalDateTime from,
                               @Param("to")     LocalDateTime to);

    // 현재 processing 상태인 프로젝트 수 (동시 작업 한도 계산)
    @Query("SELECT COUNT(p) FROM UserProject p WHERE p.userId = :userId " +
           "AND p.status = 'processing' AND p.deletedAt IS NULL")
    int countActiveProjects(@Param("userId") Long userId);

    /** floor_detection_id 로 user_project 역추적 — /place 호출 시 project_id 자동 보강용 (2026-04-29 신설). */
    Optional<UserProject> findFirstByFloorDetectionId(Long floorDetectionId);
    /** floor_archive_id 로 user_project 역추적 — /space-data 호출 시 project_id 자동 보강용 (2026-04-29 신설). */
    Optional<UserProject> findFirstByFloorArchiveIdOrderByIdDesc(Long floorArchiveId);

    // 2026-05-04 (H1 fix) - attach* race 방지. WHERE col IS NULL conditional update.
    // JPA save() 의 dirty checking 이 전체 row UPDATE 라 동시 attach 시 stale 값으로 덮어쓰기 발생.
    // 본 메서드는 컬럼별 조건부 UPDATE → race 자체 발생 X. 이미 박혀 있으면 0 반환 (silently no-op + service 단에서 log warning).

    @Modifying
    @Query("UPDATE UserProject p SET p.floorArchiveId = :archiveId WHERE p.id = :pid AND p.floorArchiveId IS NULL")
    int attachFloorArchiveIfAbsent(@Param("pid") Long pid, @Param("archiveId") Long archiveId);

    @Modifying
    @Query("UPDATE UserProject p SET p.brandManualId = :manualId WHERE p.id = :pid AND p.brandManualId IS NULL")
    int attachBrandManualIfAbsent(@Param("pid") Long pid, @Param("manualId") Long manualId);

    @Modifying
    @Query("UPDATE UserProject p SET p.floorDetectionId = :detectionId WHERE p.id = :pid AND p.floorDetectionId IS NULL")
    int attachFloorDetectionIfAbsent(@Param("pid") Long pid, @Param("detectionId") Long detectionId);
}
