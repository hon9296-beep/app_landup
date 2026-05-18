package com.landup.common;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "brand_categories")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BrandCategory {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 50)
    private String code;

    @Column(nullable = false, length = 50)
    private String nameKo;

    @Column(nullable = false, length = 100)
    private String folderName;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isActive = true;
}
