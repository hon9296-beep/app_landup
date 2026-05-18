package com.landup.plan;

import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/me")
@RequiredArgsConstructor
public class PlanLimitController {

    private final PlanLimitService planLimitService;
    private final CreditService creditService;

    @GetMapping("/plan-limits")
    public ResponseEntity<PlanLimitStatus> getPlanLimits(
            @AuthenticationPrincipal User user) {
        return ResponseEntity.ok(planLimitService.getLimitStatus(user));
    }

    @GetMapping("/credit-history")
    public ResponseEntity<List<CreditTransactionDto>> getCreditHistory(
            @AuthenticationPrincipal User user) {
        return ResponseEntity.ok(creditService.getTransactions(user.getId()));
    }
}
