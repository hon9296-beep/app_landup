package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 진규 fixture_directional_clearance 흡수 (1:1).
 */
@Entity
@Table(name = "object_clearance")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectClearance {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private Long objectPaletteId;

    @Column(nullable = false)
    @Builder.Default
    private Integer frontMm = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer backMm = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer frontFloorMm = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer backFloorMm = 0;
}
