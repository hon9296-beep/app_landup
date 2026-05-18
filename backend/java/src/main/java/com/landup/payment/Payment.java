package com.landup.payment;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "payments", indexes = {
        @Index(name = "idx_payments_user", columnList = "userId"),
        @Index(name = "idx_payments_order", columnList = "orderId")
})
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class Payment {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    private Long paymentMethodId;

    @Column(nullable = false, unique = true, length = 100)
    private String orderId;

    @Column(length = 200)
    private String paymentKey;

    @Column(nullable = false)
    private Integer amount;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    @Column(nullable = false, length = 20)
    private PaymentStatus status = PaymentStatus.pending;

    @Column(length = 200)
    private String description;

    @Column(length = 20)
    private String planKey;

    @Column(length = 50)
    private String method;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    @Column(nullable = false, length = 20)
    private PaymentType type = PaymentType.SUBSCRIPTION;

    private LocalDateTime nextBillingDate;

    private LocalDateTime cancelledAt;

    @Builder.Default
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum PaymentStatus { pending, success, failed, cancelled }
    public enum PaymentType { SUBSCRIPTION, CREDIT }
}
