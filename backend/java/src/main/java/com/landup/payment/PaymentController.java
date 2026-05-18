package com.landup.payment;

import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/payments")
@RequiredArgsConstructor
public class PaymentController {

    private final PaymentService paymentService;

    // ── 일반결제 승인 ────────────────────────────────────────────────────
    @PostMapping("/pay/confirm")
    public ResponseEntity<Payment> confirmPayment(
            @AuthenticationPrincipal User user,
            @RequestBody Map<String, Object> body) {
        Payment payment = paymentService.confirmPayment(
                user.getId(),
                body.get("paymentKey").toString(),
                body.get("orderId").toString(),
                Integer.valueOf(body.get("amount").toString()),
                body.get("description").toString(),
                body.getOrDefault("planKey", "").toString()
        );
        return ResponseEntity.ok(payment);
    }

    // ── 현재 활성 구독 조회 ────────────────────────────────────────────
    @GetMapping("/current")
    public ResponseEntity<Payment> getCurrentSubscription(
            @AuthenticationPrincipal User user) {
        return paymentService.getCurrentSubscription(user.getId())
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.noContent().build());
    }

    // ── 구독 취소 ────────────────────────────────────────────────────────
    @PostMapping("/subscription/cancel")
    public ResponseEntity<Payment> cancelSubscription(
            @AuthenticationPrincipal User user) {
        return ResponseEntity.ok(paymentService.cancelSubscription(user.getId()));
    }

    // ── 크레딧 팩 구매 ────────────────────────────────────────────────────
    @PostMapping("/credits/confirm")
    public ResponseEntity<Payment> purchaseCredits(
            @AuthenticationPrincipal User user,
            @RequestBody Map<String, Object> body) {
        Payment payment = paymentService.purchaseCredits(
                user.getId(),
                body.get("paymentKey").toString(),
                body.get("orderId").toString(),
                Integer.valueOf(body.get("amount").toString()),
                Integer.valueOf(body.get("creditAmount").toString())
        );
        return ResponseEntity.ok(payment);
    }

    // ── 결제 내역 조회 ─────────────────────────────────────────────────
    @GetMapping("/history")
    public ResponseEntity<List<Payment>> getHistory(
            @AuthenticationPrincipal User user) {
        return ResponseEntity.ok(paymentService.getMyPayments(user.getId()));
    }
}
