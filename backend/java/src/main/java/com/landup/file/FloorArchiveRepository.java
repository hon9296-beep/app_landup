package com.landup.file;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface FloorArchiveRepository extends JpaRepository<FloorArchive, Long> {
    List<FloorArchive> findAllByUserIdOrderByCreatedAtDesc(Long userId);
    List<FloorArchive> findAllByUserIdAndStatus(Long userId, FloorArchive.FloorArchiveStatus status);

    /**
     * 박물관 retention cron 용 — cutoff 시점보다 오래된 row 의 s3_key 목록 SELECT.
     * S3 삭제 위해 DB DELETE 전에 호출.
     */
    @Query("SELECT fa.s3Key FROM FloorArchive fa WHERE fa.createdAt < :cutoff AND fa.s3Key IS NOT NULL")
    List<String> findS3KeysOlderThan(@Param("cutoff") LocalDateTime cutoff);

    /**
     * 박물관 retention cron 용 — cutoff 시점보다 오래된 row bulk DELETE.
     * floor_detections.floor_archive_id 는 ON DELETE SET NULL 자동 처리 (분석 결과 영구).
     */
    @Modifying
    @Query("DELETE FROM FloorArchive fa WHERE fa.createdAt < :cutoff")
    int deleteOlderThan(@Param("cutoff") LocalDateTime cutoff);
}
