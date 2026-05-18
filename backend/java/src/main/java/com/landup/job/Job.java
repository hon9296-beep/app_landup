package com.landup.job;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 기준 패치판 — 기존 Job 대체.
 * 변경점:
 *   - progress(JSON) → progress_stage/pct/message 로 3컬럼 분리
 *   - indexes: idx_status_created → idx_user_created 로 변경
 */
@Entity
@Table(name = "jobs", indexes = {
        @Index(name = "idx_user_status", columnList = "userId,status"),
        @Index(name = "idx_user_created", columnList = "userId,createdAt DESC")
})
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class Job {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private JobType jobType;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    @Column(nullable = false, length = 20)
    private JobState status = JobState.pending;

    @Column(length = 50)
    private String progressStage;

    @Column(nullable = false)
    @Builder.Default
    private Integer progressPct = 0;

    @Column(length = 255)
    private String progressMessage;

    /** 완료 시 user_projects FK. 실패/진행중엔 NULL. */
    private Long resultProjectId;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Builder.Default
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    private LocalDateTime startedAt;
    private LocalDateTime completedAt;

    public enum JobType { detect, brand, space_data, place, export }
    public enum JobState { pending, running, done, error, cancelled }
}
