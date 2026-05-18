package com.landup.placement;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — 진규 failed_object 흡수.
 * 배치 실패한 오브젝트와 사유 기록.
 */
@Entity
@Table(name = "placement_failed_objects",
       indexes = {
           @Index(name = "idx_result", columnList = "placementResultId"),
           @Index(name = "idx_type", columnList = "objectType")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class PlacementFailedObject {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long placementResultId;

    @Column(nullable = false, length = 64)
    private String objectType;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String reason;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();
}
