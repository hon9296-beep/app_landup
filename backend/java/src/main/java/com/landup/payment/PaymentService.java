package com.landup.payment;

import com.landup.common.ApiException;
import com.landup.plan.CreditService;
import com.landup.user.User;
import com.landup.user.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class PaymentService {

    private final PaymentRepository paymentRepository;
    private final UserRepository userRepository;
    private final CreditService creditService;

    @Value("${toss.secret-key}")
    private String tossSecretKey;

    private static final String TOSS_API = "https://api.tosspayments.com/v1";

    // ── 일반결제 승인 ────────────────────────────────────────────────────

    @Transactional
    public Payment confirmPayment(Long userId, String paymentKey,
                                  String orderId, Integer amount, String description, String planKey) {
        String method = confirmTossPayment(paymentKey, orderId, amount);

        Payment payment = Payment.builder()
                .userId(userId)
                .orderId(orderId)
                .paymentKey(paymentKey)
                .amount(amount)
                .status(Payment.PaymentStatus.success)
                .type(Payment.PaymentType.SUBSCRIPTION)
                .description(description)
                .planKey(planKey)
                .method(method)
                .nextBillingDate(LocalDateTime.now().plusMonths(1))
                .build();

        paymentRepository.save(payment);

        // 유저 멤버십 업그레이드 + planStartedAt 리셋
        userRepository.findById(userId).ifPresent(user -> {
            try {
                user.setMembership(User.Membership.valueOf(planKey));
                user.setPlanStartedAt(LocalDateTime.now());
                userRepository.save(user);
            } catch (IllegalArgumentException ignored) {}
        });

        return payment;
    }

    // ── 크레딧 팩 구매 ────────────────────────────────────────────────────

    @Transactional
    public Payment purchaseCredits(Long userId, String paymentKey,
                                   String orderId, Integer amount, int creditAmount) {
        String method = confirmTossPayment(paymentKey, orderId, amount);

        Payment payment = Payment.builder()
                .userId(userId)
                .orderId(orderId)
                .paymentKey(paymentKey)
                .amount(amount)
                .status(Payment.PaymentStatus.success)
                .type(Payment.PaymentType.CREDIT)
                .description(creditAmount + " 크레딧 구매")
                .method(method)
                .build();

        paymentRepository.save(payment);
        creditService.charge(userId, creditAmount);

        return payment;
    }

    // ── 현재 활성 구독 조회 ────────────────────────────────────────────

    @Transactional(readOnly = true)
    public Optional<Payment> getCurrentSubscription(Long userId) {
        return paymentRepository.findTopByUserIdAndStatusAndTypeOrderByCreatedAtDesc(
                userId, Payment.PaymentStatus.success, Payment.PaymentType.SUBSCRIPTION);
    }

    // ── 구독 취소 ────────────────────────────────────────────────────────

    @Transactional
    public Payment cancelSubscription(Long userId) {
        Payment payment = paymentRepository
                .findTopByUserIdAndStatusOrderByCreatedAtDesc(userId, Payment.PaymentStatus.success)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "활성 구독이 없습니다"));

        if (payment.getCancelledAt() != null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "이미 취소된 구독입니다");
        }

        payment.setCancelledAt(LocalDateTime.now());
        return paymentRepository.save(payment);
    }

    // ── 관리자 결제 취소 (Toss 환불 + DB 업데이트) ─────────────────────

    @Transactional
    public Payment cancelPaymentByAdmin(Long paymentId, String reason) {
        Payment payment = paymentRepository.findById(paymentId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "결제를 찾을 수 없습니다."));

        if (payment.getStatus() == Payment.PaymentStatus.cancelled) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "이미 취소된 결제입니다.");
        }
        if (payment.getPaymentKey() == null || payment.getPaymentKey().isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "결제 키가 없어 환불할 수 없습니다.");
        }

        String body = String.format("{\"cancelReason\":\"%s\"}", reason != null ? reason : "관리자 환불");
        try {
            HttpResponse<String> res = tossPost("/payments/" + payment.getPaymentKey() + "/cancel", body);
            if (res.statusCode() != 200) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "Toss 환불 실패: " + res.body());
            }
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "Toss API 오류: " + e.getMessage());
        }

        payment.setStatus(Payment.PaymentStatus.cancelled);
        payment.setCancelledAt(LocalDateTime.now());
        return paymentRepository.save(payment);
    }

    // ── 결제 내역 조회 ─────────────────────────────────────────────────

    @Transactional(readOnly = true)
    public List<Payment> getMyPayments(Long userId) {
        return paymentRepository.findByUserIdOrderByCreatedAtDesc(userId);
    }

    // ── 토스 결제 승인 API 호출 ────────────────────────────────────────

    private String confirmTossPayment(String paymentKey, String orderId, Integer amount) {
        try {
            String body = String.format(
                    "{\"paymentKey\":\"%s\",\"orderId\":\"%s\",\"amount\":%d}",
                    paymentKey, orderId, amount);
            HttpResponse<String> res = tossPost("/payments/confirm", body);
            if (res.statusCode() != 200) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "결제 승인 실패: " + res.body());
            }
            // 간편결제(네이버페이/토스페이 등)는 easyPay.provider, 카드는 method 값 사용
            JsonNode json = new ObjectMapper().readTree(res.body());
            JsonNode easyPay = json.path("easyPay").path("provider");
            if (!easyPay.isMissingNode() && !easyPay.asText().isBlank()) {
                return easyPay.asText();
            }
            return json.path("method").asText("카드");
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "토스 API 오류: " + e.getMessage());
        }
    }

    private HttpResponse<String> tossPost(String path, String body) throws Exception {
        String encoded = Base64.getEncoder().encodeToString((tossSecretKey + ":").getBytes());
        HttpRequest req = HttpRequest.newBuilder()
                .uri(URI.create(TOSS_API + path))
                .header("Authorization", "Basic " + encoded)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body))
                .build();
        return HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
    }
}
