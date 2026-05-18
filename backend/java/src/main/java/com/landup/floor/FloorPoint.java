package com.landup.floor;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 도면의 주요 포인트(출입문/비상구/스프링클러/소화전/배전반).
 */
@Entity
@Table(name = "floor_points",
       indexes = @Index(name = "idx_floor_type", columnList = "floorDetectionId,type"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorPoint {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private PointType type;

    @Column(nullable = false)
    private Float xMm;

    @Column(nullable = false)
    private Float yMm;

    private Float widthMm;

    private Boolean isMain;

    public enum PointType { main_door, emergency_exit, sprinkler, fire_hydrant, electrical_panel }
}
