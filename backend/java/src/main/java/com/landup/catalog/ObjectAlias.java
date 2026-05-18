package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "object_aliases")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectAlias {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long objectPaletteId;

    @Column(nullable = false, unique = true, length = 100)
    private String alias;
}
