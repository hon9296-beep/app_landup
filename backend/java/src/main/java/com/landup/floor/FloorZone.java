package com.landup.floor;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 진규 zone_polygon (entrance/mid/deep 구역).
 */
@Entity
@Table(name = "floor_zones",
       uniqueConstraints = @UniqueConstraint(name = "uk_floor_zone", columnNames = {"floorDetectionId", "zoneLabel"}),
       indexes = @Index(name = "idx_floor", columnList = "floorDetectionId"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorZone {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private ZoneLabel zoneLabel;

    @Column(nullable = false, columnDefinition = "MEDIUMTEXT")
    private String polygonJson;

    public enum ZoneLabel { entrance_zone, mid_zone, deep_zone }
}
