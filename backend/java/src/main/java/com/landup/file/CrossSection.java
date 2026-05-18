package com.landup.file;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "cross_sections",
       indexes = {
           @Index(name = "idx_user", columnList = "userId"),
           @Index(name = "idx_floor_detection", columnList = "floorDetectionId")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class CrossSection {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    private Long floorDetectionId;

    @Column(nullable = false, length = 500)
    private String originalFilename;

    @Column(nullable = false, length = 500)
    private String storedFilename;

    @Column(nullable = false, length = 10)
    @Builder.Default
    private String fileType = "pdf";

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private CrossSectionStatus status = CrossSectionStatus.processing;

    @Column(name = "section_ceiling_mm")
    private Float sectionCeilingMm;

    private Float confidence;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    void onUpdate() { this.updatedAt = LocalDateTime.now(); }

    public enum CrossSectionStatus { processing, done, error }
}
