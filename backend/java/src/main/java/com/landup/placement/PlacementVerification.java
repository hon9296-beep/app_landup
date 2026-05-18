package com.landup.placement;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — 검증 위반/경고 로그.
 */
@Entity
@Table(name = "placement_verifications",
       indexes = @Index(name = "idx_result_severity", columnList = "placementResultId,severity"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class PlacementVerification {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long placementResultId;

    private Long placementObjectId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private Rule rule;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Severity severity;

    @Column(columnDefinition = "TEXT")
    private String detail;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum Rule { floor_exit, dead_zone, main_artery, pair_separate, corridor, wall_clearance, emergency_exit }
    public enum Severity { blocking, warning }
}
