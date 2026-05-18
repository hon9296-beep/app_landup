package com.landup.plan;

import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

@Getter
@Builder
public class CreditTransactionDto {
    private Long id;
    private Long userId;
    private Integer amount;
    private CreditTransaction.CreditType type;
    private Long projectId;
    private String projectName;
    private LocalDateTime createdAt;
}
