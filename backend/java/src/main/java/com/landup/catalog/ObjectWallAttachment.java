package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — 진규 fixture_wall_attachment 흡수 (1:1).
 */
@Entity
@Table(name = "object_wall_attachment")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectWallAttachment {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true)
    private Long objectPaletteId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Attachment attachment;

    public enum Attachment { flush, near, free, either }
}
