package com.landup.placement;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 (기존 PlacementObject 스키마 전면 개편).
 * 변경점:
 *   - floorDetectionId → placementResultId 로 상위 키 이동
 *   - furnitureStandardId 제거, objectType/floorAnchorId 로 대체
 *   - zone_label / direction / alignment / wall_attachment 메타 추가
 *   - 2026-05-10 label 컬럼 복원 — Python placed_objects 의 한국어 라벨 (예: "카운터")
 *     을 프론트에 그대로 노출. 영문 std_id (objectType, 예: "counter") 와 별도 필드.
 */
@Entity
@Table(name = "placement_objects",
       indexes = {
           @Index(name = "idx_result", columnList = "placementResultId"),
           @Index(name = "idx_anchor", columnList = "floorAnchorId"),
           @Index(name = "idx_type", columnList = "objectType")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class PlacementObject {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long placementResultId;

    @Column(nullable = false, length = 64)
    private String objectType;

    @Column(length = 100)
    private String label;

    private Long floorAnchorId;

    @Column(nullable = false)
    private Float centerXMm;

    @Column(nullable = false)
    private Float centerYMm;

    @Column(nullable = false)
    @Builder.Default
    private Float rotationDeg = 0f;

    @Column(nullable = false)
    private Float widthMm;

    @Column(nullable = false)
    private Float depthMm;

    @Column(nullable = false)
    private Float heightMm;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private ZoneLabel zoneLabel;

    /** 2026-05-01 Phase 2 — concept_areas FK (large 전용, small 은 NULL). */
    private Long conceptAreaId;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private Direction direction;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private Alignment alignment;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private WallAttachment wallAttachment;

    @Column(length = 50)
    private String category;

    /** 2026-05-10 — partition_wall 의 graphic_face (none/inner/outer/both). 기타 obj 는 'none'.
     *  partition_reuse 노드가 photo_wall 흡수 시 'outer' 로 박음. frontend 시각 구분용. */
    @Column(length = 16)
    private String graphicFace;

    /** 2026-05-10 — graphic_face 의 basis (default_front / photo_wall_substitute / ...). */
    @Column(length = 32)
    private String graphicFaceBasis;

    @Column(columnDefinition = "TEXT")
    private String placedBecause;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum ZoneLabel { entrance_zone, mid_zone, deep_zone }
    public enum Direction { wall_facing, center, inward, focal, outward, freestanding }
    public enum Alignment { parallel, perpendicular, none, opposite }
    public enum WallAttachment { flush, near, free, either }
}
