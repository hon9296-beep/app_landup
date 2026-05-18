package com.landup.catalog;

import jakarta.persistence.*;
import lombok.*;

/**
 * init_v2.sql 신규 — VMD_PAIR_RULES seed.
 * small 프롬프트 + large merge/verify 단계에서 조회.
 */
@Entity
@Table(name = "object_pair_rules",
       uniqueConstraints = @UniqueConstraint(name = "uk_pair_rule",
               columnNames = {"objectACode", "objectBCode", "relation", "source"}),
       indexes = {
           @Index(name = "idx_a_code", columnList = "objectACode"),
           @Index(name = "idx_source", columnList = "source")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ObjectPairRule {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 64)
    private String objectACode;

    @Column(nullable = false, length = 64)
    private String objectBCode;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Relation relation;

    @Column(nullable = false)
    @Builder.Default
    private Integer minGapMm = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer overlapMarginMm = 0;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private Source source = Source.vmd_default;

    public enum Relation { join, adjacent, separate }
    public enum Source { vmd_default, manual }
}
