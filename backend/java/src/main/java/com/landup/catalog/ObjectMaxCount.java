package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "object_max_count",
       uniqueConstraints = @UniqueConstraint(name = "uk_palette_category", columnNames = {"objectPaletteId", "brandCategory"}))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectMaxCount {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long objectPaletteId;

    @Column(length = 50)
    private String brandCategory;

    @Column(nullable = false)
    private Short maxCount;
}
