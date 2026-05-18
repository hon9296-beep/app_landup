package com.landup.payment;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface PaymentRepository extends JpaRepository<Payment, Long> {
    List<Payment> findByUserIdOrderByCreatedAtDesc(Long userId);
    List<Payment> findByUserIdInOrderByCreatedAtDesc(Collection<Long> userIds);
    Optional<Payment> findByOrderId(String orderId);
    Optional<Payment> findTopByUserIdAndStatusOrderByCreatedAtDesc(Long userId, Payment.PaymentStatus status);
    Optional<Payment> findTopByUserIdAndStatusAndTypeOrderByCreatedAtDesc(Long userId, Payment.PaymentStatus status, Payment.PaymentType type);
}
