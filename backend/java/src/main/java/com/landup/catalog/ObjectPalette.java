package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — OBJECT_STANDARDS 카탈로그 정본.
 * 기존 FurnitureStandard 완전 대체.
 * wall_attachment / clearance 는 1:1 별도 테이블로 분리됨.
 */
@Entity
@Table(name = "object_palette",
       indexes = @Index(name = "idx_fixture_role", columnList = "fixtureRole"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectPalette {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 64)
    private String code;

    @Column(nullable = false, length = 100)
    private String nameKo;

    @Column(nullable = false)
    @Builder.Default
    private Integer priority = 50;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    @Builder.Default
    private FrontEdge frontEdge = FrontEdge.width;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isStructural = false;

    @Column(length = 32)
    private String fixtureRole;

    @Column(nullable = false)
    private Float widthStdMm;

    @Column(nullable = false)
    private Float depthStdMm;

    @Column(nullable = false)
    private Float heightStdMm;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum FrontEdge { width, depth }
}
