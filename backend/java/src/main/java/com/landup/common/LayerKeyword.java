package com.landup.common;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "layer_keywords",
       uniqueConstraints = @UniqueConstraint(name = "uk_category_keyword", columnNames = {"category", "keyword"}),
       indexes = @Index(name = "idx_category", columnList = "category"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class LayerKeyword {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private LayerCategory category;

    @Column(nullable = false, length = 100)
    private String keyword;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isActive = true;

    public enum LayerCategory { entrance, emergency, inaccessible, sprinkler, hydrant, panel }
}
