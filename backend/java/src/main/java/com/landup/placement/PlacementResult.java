package com.landup.placement;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — 배치 결과 최상위.
 * FloorDetection 기반 1:N. placement_objects / verifications / cap_logs / failed_objects / token_usage 가 하위.
 */
@Entity
@Table(name = "placement_results",
       indexes = {
           @Index(name = "idx_floor", columnList = "floorDetectionId"),
           @Index(name = "idx_status_created", columnList = "status,createdAt DESC")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class PlacementResult {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private ResultStatus status = ResultStatus.processing;

    private Float densityRatio;

    @Column(columnDefinition = "TEXT")
    private String userRequirements;

    @Column(nullable = false)
    @Builder.Default
    private Integer placedCount = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer failedCount = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer fallbackRound = 0;

    private Boolean verificationPassed;
    private Float refQualityScore;

    @Column(columnDefinition = "TEXT")
    private String reportText;

    @Column(columnDefinition = "MEDIUMTEXT")
    private String reportJson;

    @Column(length = 500)
    private String glbPath;

    /**
     * 2026-05-04 신설 — 부동선 (sub_path) 좌표 JSON.
     * 형식: [[x_mm, y_mm], [x_mm, y_mm], ...]. 빈 list / null 가능.
     * Python pathing_validator 노드가 만든 부수 동선 (현재는 비활성, 추후 large 분기에서 주동선 fallback 확장 형식으로 사용 예정).
     * 프론트 Viewer3D 가 받아서 시각화.
     */
    @Column(columnDefinition = "TEXT")
    private String subPathJson;

    /**
     * 2026-05-04 신설 — 주동선 (main_artery) 좌표 JSON.
     * 형식: [[x_mm, y_mm], [x_mm, y_mm], ...]. 빈 list / null 가능.
     * Python walk_mm 노드가 배치 후 계산한 주동선 (순환 동선 또는 일자 fallback).
     * 변경 전엔 floor_detection (space_data) 에 박혀있었으나 walk_mm 이 place 단계로 이동하면서 placement_results 로 이동.
     * 프론트 Viewer3D 가 받아서 시각화.
     */
    @Column(columnDefinition = "TEXT")
    private String mainArteryJson;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum ResultStatus { processing, done, error }
}
