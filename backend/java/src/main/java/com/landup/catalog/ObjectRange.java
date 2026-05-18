package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "object_ranges",
       uniqueConstraints = @UniqueConstraint(name = "uk_palette_category", columnNames = {"objectPaletteId", "brandCategory"}))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectRange {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long objectPaletteId;

    @Column(length = 50)
    private String brandCategory;

    @Column(nullable = false)
    private Float widthMinMm;

    @Column(nullable = false)
    private Float widthMaxMm;

    @Column(nullable = false)
    private Float depthMinMm;

    @Column(nullable = false)
    private Float depthMaxMm;

    @Column(nullable = false)
    private Float heightMinMm;

    @Column(nullable = false)
    private Float heightMaxMm;
}
