package com.landup.common;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "brand_defaults")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BrandDefaults {

    @Id
    @Builder.Default
    private Long id = 1L;

    @Column(nullable = false)
    @Builder.Default
    private Integer clearspaceMm = 900;

    @Column(nullable = false)
    @Builder.Default
    private Integer logoClearspaceMm = 500;

    @Column(nullable = false, length = 20)
    @Builder.Default
    private String characterOrientation = "자유";

    @Column(nullable = false)
    @Builder.Default
    private Integer mainCorridorMinMm = 900;

    @Column(nullable = false)
    @Builder.Default
    private Integer emergencyPathMinMm = 1200;

    @Column(nullable = false)
    @Builder.Default
    private Integer wallClearanceMm = 300;

    @Column(nullable = false)
    @Builder.Default
    private Integer objectGapMm = 300;

    @Column(nullable = false)
    @Builder.Default
    private Integer mainArteryHalfBufferMm = 600;

    @Column(nullable = false)
    @Builder.Default
    private Integer corridorHalfBufferMm = 450;

    @Column(nullable = false)
    @Builder.Default
    private Integer innerWallBufferMm = 150;

    @Column(nullable = false)
    @Builder.Default
    private Integer defaultHeightMm = 1500;

    @Column(nullable = false)
    @Builder.Default
    private Float maxDensityRatio = 0.25f;

    @Column(nullable = false)
    @Builder.Default
    private Integer maxFallbackRounds = 3;

    @Column(nullable = false)
    @Builder.Default
    private Long scalingReferenceAreaMm2 = 99_000_000L;

    @Column(nullable = false)
    @Builder.Default
    private Integer stepDownMm = 200;

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    void onUpdate() { this.updatedAt = LocalDateTime.now(); }
}
