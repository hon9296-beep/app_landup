package com.landup.job;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 신규 — 진규 LLM 비용 집계.
 * PlacementResult × node_name 단위로 토큰 사용량 누적.
 */
@Entity
@Table(name = "token_usage",
       uniqueConstraints = @UniqueConstraint(name = "uk_result_node", columnNames = {"placementResultId", "nodeName"}),
       indexes = {
           @Index(name = "idx_result", columnList = "placementResultId"),
           @Index(name = "idx_model_time", columnList = "model,calledAt DESC")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class TokenUsage {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long placementResultId;

    @Column(nullable = false, length = 64)
    private String nodeName;

    @Column(nullable = false)
    @Builder.Default
    private Integer inputTokens = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer outputTokens = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer cacheReadTokens = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer cacheWriteTokens = 0;

    @Column(length = 64)
    private String model;

    @Builder.Default
    private LocalDateTime calledAt = LocalDateTime.now();
}
