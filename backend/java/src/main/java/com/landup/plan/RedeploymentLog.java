package com.landup.plan;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "redeployment_logs", indexes = {
        @Index(name = "idx_rl_user",    columnList = "userId"),
        @Index(name = "idx_rl_project", columnList = "projectId")
})
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RedeploymentLog {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false)
    private Long projectId;

    @Builder.Default
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();
}
