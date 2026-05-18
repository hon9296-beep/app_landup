package com.landup.placement;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — 진규 space_cap 적용 로그.
 * 오브젝트 개수가 cap 에 의해 조정된 이력.
 */
@Entity
@Table(name = "placement_cap_logs",
       indexes = @Index(name = "idx_result", columnList = "placementResultId"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class PlacementCapLog {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long placementResultId;

    @Column(nullable = false, length = 64)
    private String objectType;

    @Column(nullable = false, length = 96)
    private String dimension;

    @Column(nullable = false)
    private Integer fromCount;

    @Column(nullable = false)
    private Integer toCount;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String reason;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();
}
