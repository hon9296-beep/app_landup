package com.landup.floor;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 접근불가/데드존 폴리곤.
 */
@Entity
@Table(name = "floor_polygons",
       indexes = @Index(name = "idx_floor_kind", columnList = "floorDetectionId,kind"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorPolygon {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Kind kind;

    @Column(nullable = false, length = 30)
    private String source;

    @Column(nullable = false, columnDefinition = "MEDIUMTEXT")
    private String polygonJson;

    private Float centerXMm;

    private Float centerYMm;

    private Float radiusMm;

    public enum Kind { inaccessible, dead_zone }
}
