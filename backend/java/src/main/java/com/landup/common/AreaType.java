package com.landup.common;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "area_types")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class AreaType {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 50)
    private String code;

    @Column(nullable = false, length = 50)
    private String nameKo;

    @Column(nullable = false, columnDefinition = "JSON")
    private String targetObjects;

    @Column(length = 50)
    private String positionHint;

    @Column(columnDefinition = "TEXT")
    private String description;

    @Column(nullable = false)
    @Builder.Default
    private Integer displayOrder = 0;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isActive = true;
}
