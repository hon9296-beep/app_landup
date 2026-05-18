package com.landup.project;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 기준 패치판 — 기존 UserProject 대체.
 * 변경점:
 *   - pdfFileId → pdfId 리네임
 *   - brandAnalysisId → brandManualId 리네임
 *   - placementResultId FK 추가 (신규)
 *   - 2026-04-27: pdfId → floorArchiveId rename (pdf 테이블 → floor_archive 박물관 일관)
 */
@Entity
@Table(name = "user_projects", indexes = {
        @Index(name = "idx_user_status", columnList = "userId,status"),
        @Index(name = "idx_user_created", columnList = "userId,createdAt DESC")
})
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class UserProject {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Column(length = 200)
    private String name;

    private Long floorArchiveId;
    private Long brandManualId;
    private Long floorDetectionId;
    private Long placementResultId;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    @Column(nullable = false, length = 20)
    private ProjectState status = ProjectState.processing;

    private LocalDateTime deletedAt;

    @Builder.Default
    @Column(nullable = false)
    private Boolean wasDone = false;

    @Builder.Default
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    void onUpdate() { this.updatedAt = LocalDateTime.now(); }

    public enum ProjectState { processing, done, error }
}
