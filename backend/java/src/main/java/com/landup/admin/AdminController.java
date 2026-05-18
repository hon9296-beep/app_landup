package com.landup.admin;

import com.landup.common.ApiException;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;

/**
 * 관리자 전용 API
 *
 * GET  /admin/users?page=0&size=10&search=  → 회원 + 결제 내역 페이징 조회
 * PATCH /admin/users/{id}                   → 회원 이름·전화번호 수정
 * PATCH /admin/payments/{id}                → 결제 status·next_billing_date 수정
 */
@RestController
@RequestMapping("/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;

    private void requireAdmin(User user) {
        if (!Boolean.TRUE.equals(user.getIsAdmin())) {
            throw new ApiException(HttpStatus.FORBIDDEN, "관리자만 접근 가능합니다.");
        }
    }

    @GetMapping("/users")
    public Page<AdminService.AdminUserDto> getAllUsers(
            @AuthenticationPrincipal User user,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "10") int size,
            @RequestParam(required = false, defaultValue = "") String search) {
        requireAdmin(user);
        return adminService.getAllUsersWithPayments(page, size, search);
    }

    record UserPatchRequest(String name, String phone) {}

    @PatchMapping("/users/{id}")
    public AdminService.AdminUserDto updateUser(
            @AuthenticationPrincipal User user,
            @PathVariable Long id,
            @RequestBody UserPatchRequest req) {
        requireAdmin(user);
        return adminService.updateUser(id, req.name(), req.phone());
    }

    record PaymentPatchRequest(String status, LocalDateTime nextBillingDate) {}

    @PatchMapping("/payments/{id}")
    public AdminService.PaymentSummaryDto updatePayment(
            @AuthenticationPrincipal User user,
            @PathVariable Long id,
            @RequestBody PaymentPatchRequest req) {
        requireAdmin(user);
        return adminService.updatePayment(id, req.status(), req.nextBillingDate());
    }

    record PaymentCancelRequest(String reason) {}

    @PostMapping("/payments/{id}/cancel")
    public AdminService.PaymentSummaryDto cancelPayment(
            @AuthenticationPrincipal User user,
            @PathVariable Long id,
            @RequestBody(required = false) PaymentCancelRequest req) {
        requireAdmin(user);
        return adminService.cancelPayment(id, req != null ? req.reason() : null);
    }
}
