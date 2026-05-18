package com.landup.admin;

import com.landup.auth.GoogleOAuthRepository;
import com.landup.auth.KakaoOAuthRepository;
import com.landup.auth.NaverOAuthRepository;
import com.landup.common.ApiException;
import com.landup.payment.Payment;
import com.landup.payment.PaymentRepository;
import com.landup.payment.PaymentService;
import com.landup.user.User;
import com.landup.user.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class AdminService {

    private final UserRepository userRepository;
    private final PaymentRepository paymentRepository;
    private final PaymentService paymentService;
    private final NaverOAuthRepository naverOAuthRepository;
    private final GoogleOAuthRepository googleOAuthRepository;
    private final KakaoOAuthRepository kakaoOAuthRepository;

    public record PaymentSummaryDto(
            Long id,
            Integer amount,
            LocalDateTime createdAt,
            LocalDateTime cancelledAt,
            String description,
            String method,
            LocalDateTime nextBillingDate,
            String status
    ) {}

    public record AdminUserDto(
            Long id,
            String name,
            String phone,
            String email,
            String membership,
            LocalDateTime createdAt,
            Boolean isVerified,
            String authMethod,
            List<PaymentSummaryDto> payments
    ) {}

    public Page<AdminUserDto> getAllUsersWithPayments(int page, int size, String search) {
        String q = (search == null) ? "" : search.trim();
        PageRequest pageable = PageRequest.of(page, size, Sort.by(Sort.Direction.DESC, "id"));

        Page<User> userPage = userRepository.searchUsers(q, pageable);

        // 현재 페이지 유저 ID 목록으로 결제 내역 + OAuth 여부 조회
        Set<Long> userIds = userPage.getContent().stream()
                .map(User::getId)
                .collect(Collectors.toSet());

        Map<Long, List<Payment>> paymentsByUser = userIds.isEmpty()
                ? Map.of()
                : paymentRepository.findByUserIdInOrderByCreatedAtDesc(userIds).stream()
                        .collect(Collectors.groupingBy(Payment::getUserId));

        Set<Long> naverUserIds = userIds.isEmpty() ? Set.of()
                : naverOAuthRepository.findByUserIdIn(userIds).stream()
                        .map(o -> o.getUserId()).collect(Collectors.toSet());
        Set<Long> googleUserIds = userIds.isEmpty() ? Set.of()
                : googleOAuthRepository.findByUserIdIn(userIds).stream()
                        .map(o -> o.getUserId()).collect(Collectors.toSet());
        Set<Long> kakaoUserIds = userIds.isEmpty() ? Set.of()
                : kakaoOAuthRepository.findByUserIdIn(userIds).stream()
                        .map(o -> o.getUserId()).collect(Collectors.toSet());

        return userPage.map(user -> {
            List<PaymentSummaryDto> payments = paymentsByUser
                    .getOrDefault(user.getId(), List.of())
                    .stream()
                    .sorted(Comparator.comparing(Payment::getCreatedAt).reversed())
                    .map(p -> new PaymentSummaryDto(
                            p.getId(), p.getAmount(), p.getCreatedAt(),
                            p.getCancelledAt(), p.getDescription(),
                            p.getMethod(), p.getNextBillingDate(),
                            p.getStatus().name()
                    ))
                    .toList();
            String authMethod = resolveAuthMethod(user.getId(), naverUserIds, googleUserIds, kakaoUserIds);
            return new AdminUserDto(
                    user.getId(), user.getName(), user.getPhone(), user.getEmail(),
                    user.getMembership().name(), user.getCreatedAt(),
                    user.getIsVerified(), authMethod, payments
            );
        });
    }

    @Transactional
    public AdminUserDto updateUser(Long userId, String name, String phone) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "user not found: " + userId));
        if (name != null) user.setName(name);
        if (phone != null) user.setPhone(phone);
        userRepository.save(user);

        List<Payment> payments = paymentRepository.findByUserIdOrderByCreatedAtDesc(userId);
        List<PaymentSummaryDto> paymentDtos = payments.stream()
                .map(p -> new PaymentSummaryDto(
                        p.getId(), p.getAmount(), p.getCreatedAt(),
                        p.getCancelledAt(), p.getDescription(),
                        p.getMethod(), p.getNextBillingDate(), p.getStatus().name()
                ))
                .toList();
        String authMethod = resolveAuthMethod(userId,
                naverOAuthRepository.existsByUserId(userId) ? Set.of(userId) : Set.of(),
                googleOAuthRepository.existsByUserId(userId) ? Set.of(userId) : Set.of(),
                kakaoOAuthRepository.existsByUserId(userId) ? Set.of(userId) : Set.of());
        return new AdminUserDto(
                user.getId(), user.getName(), user.getPhone(), user.getEmail(),
                user.getMembership().name(), user.getCreatedAt(),
                user.getIsVerified(), authMethod, paymentDtos
        );
    }

    private String resolveAuthMethod(Long userId, Set<Long> naverIds, Set<Long> googleIds, Set<Long> kakaoIds) {
        if (naverIds.contains(userId)) return "네이버 로그인";
        if (googleIds.contains(userId)) return "구글 로그인";
        if (kakaoIds.contains(userId)) return "카카오 로그인";
        return "";
    }

    public PaymentSummaryDto cancelPayment(Long paymentId, String reason) {
        Payment payment = paymentService.cancelPaymentByAdmin(paymentId, reason);
        return new PaymentSummaryDto(
                payment.getId(), payment.getAmount(), payment.getCreatedAt(),
                payment.getCancelledAt(), payment.getDescription(),
                payment.getMethod(), payment.getNextBillingDate(), payment.getStatus().name()
        );
    }

    @Transactional
    public PaymentSummaryDto updatePayment(Long paymentId, String status, LocalDateTime nextBillingDate) {
        Payment payment = paymentRepository.findById(paymentId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "payment not found: " + paymentId));
        if (status != null) payment.setStatus(Payment.PaymentStatus.valueOf(status.toUpperCase()));
        if (nextBillingDate != null) payment.setNextBillingDate(nextBillingDate);
        paymentRepository.save(payment);
        return new PaymentSummaryDto(
                payment.getId(), payment.getAmount(), payment.getCreatedAt(),
                payment.getCancelledAt(), payment.getDescription(),
                payment.getMethod(), payment.getNextBillingDate(), payment.getStatus().name()
        );
    }
}
