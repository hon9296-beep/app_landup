package com.landup.floor;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 레퍼런스 포인트(앵커).
 * large/small 스케일 공통. wall_normal, zone_label, walk_mm 등 공간분석 메타 포함.
 */
@Entity
@Table(name = "floor_anchors",
       uniqueConstraints = @UniqueConstraint(name = "uk_floor_anchor", columnNames = {"floorDetectionId", "anchorKey"}),
       indexes = @Index(name = "idx_floor_scale", columnList = "floorDetectionId,scale"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorAnchor {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private Scale scale;

    @Column(nullable = false, length = 100)
    private String anchorKey;

    @Column(nullable = false)
    private Float xMm;

    @Column(nullable = false)
    private Float yMm;

    @Enumerated(EnumType.STRING)
    @Column(length = 10)
    private WallNormal wallNormal;

    private Float wallAngleDeg;
    private Float wallLengthMm;

    @Column(length = 50)
    private String label;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private ZoneLabel zoneLabel;

    /** 2026-05-01 Phase 2 — concept_areas FK (large 전용, small 은 NULL). */
    private Long conceptAreaId;

    private Float walkMm;
    private Integer shelfCapacity;

    public enum Scale { large, small, outdoor }
    public enum WallNormal { N, S, E, W, NE, NW, SE, SW, none }
    public enum ZoneLabel { entrance_zone, mid_zone, deep_zone }
}
