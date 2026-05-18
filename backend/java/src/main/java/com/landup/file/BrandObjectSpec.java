package com.landup.file;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 진규 brand_placement_rule 흡수/이름변경.
 * 한 BrandManual에 대해 여러 오브젝트 규격 시퀀스(seq) 저장.
 */
@Entity
@Table(name = "brand_object_specs",
       uniqueConstraints = @UniqueConstraint(name = "uk_manual_seq", columnNames = {"brandManualId", "seq"}),
       indexes = {
           @Index(name = "idx_manual", columnList = "brandManualId"),
           @Index(name = "idx_type", columnList = "objectType")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BrandObjectSpec {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long brandManualId;

    @Column(nullable = false)
    private Short seq;

    @Column(nullable = false, length = 64)
    private String objectType;

    @Column(length = 128)
    private String name;

    private Integer widthMm;
    private Integer depthMm;
    private Integer heightMm;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private PreferredZone preferredZone;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private WallAttachment wallAttachment;

    private Integer frontClearanceMm;
    private Integer backClearanceMm;

    @Column(length = 64)
    private String requiredDirection;

    @Column(length = 64)
    private String preferredWall;

    private Short minCount;
    private Short maxCount;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    private MaxCountSource maxCountSource;

    @Column(columnDefinition = "TEXT")
    private String material;

    @Enumerated(EnumType.STRING)
    @Column(length = 10)
    private FrontEdge frontEdge;

    public enum PreferredZone { entrance_zone, mid_zone, deep_zone }
    public enum WallAttachment { flush, near, free, either }
    public enum MaxCountSource { manual, inferred }
    public enum FrontEdge { width, depth }
}
