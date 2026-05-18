package com.landup.floor;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 수정판 — 기존 FloorDetection 대체.
 * 변경점:
 *   - pdfPageId 제거 → pdfId + pageNumber 로 분리
 *   - resultJson 제거 (result 는 placement_results 로 이동)
 *   - scale/venue/usable_poly 등 공간분석 산출물 컬럼 대폭 추가
 *   - 2026-04-27: pdfId → floorArchiveId rename (pdf → floor_archive 일관)
 */
@Entity
@Table(name = "floor_detections",
       indexes = {
           @Index(name = "idx_floor_archive_page", columnList = "floorArchiveId,pageNumber"),
           @Index(name = "idx_scale_status", columnList = "scaleType,status")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorDetection {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 박물관 7일 cron 시 SET NULL — 분석 결과는 영구 (원본만 만료). */
    private Long floorArchiveId;

    @Column(nullable = false)
    private Integer pageNumber;

    private Long brandManualId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private DetectionStatus status = DetectionStatus.processing;

    private Float scaleMmPerPx;

    @Column(nullable = false)
    @Builder.Default
    private Boolean scaleConfirmed = false;

    private Float detectedWidthMm;
    private Float detectedHeightMm;
    private Float ceilingHeightMm;
    private Float usableAreaSqm;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private ScaleType scaleType;

    @Enumerated(EnumType.STRING)
    @Column(length = 30)
    private VenueType venueType;

    @Column(columnDefinition = "MEDIUMTEXT")
    private String usablePolyJson;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum DetectionStatus { processing, done, error }
    public enum ScaleType { large, small, outdoor }
    public enum VenueType { street_complex, street_standalone }
}
