package com.landup.plan;

import com.landup.common.ApiException;
import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class PlanLimitService {

    private final RedeploymentLogService redeploymentLogService;
    private final CreditService creditService;
    private final com.landup.project.UserProjectRepository userProjectRepository;

    // 플랜별 한도 상수
    private static final Map<String, int[]> PLAN_LIMITS = Map.of(
            // [프로젝트/월, 재배치/월, 동시작업]
            "basic",   new int[]{ 1, 3,  1 },
            "premium", new int[]{ 3, 10, 3 },
            "max",     new int[]{ 10, 30, 10 }
    );

    private int[] getLimits(User user) {
        return PLAN_LIMITS.getOrDefault(user.getMembership().name(), PLAN_LIMITS.get("basic"));
    }

    private LocalDateTime periodEnd(User user) {
        return user.getPlanStartedAt().plusMonths(1);
    }

    public void checkProjectLimit(User user, Long projectId) {
        if (Boolean.TRUE.equals(user.getIsAdmin())) return;

        int max  = getLimits(user)[0];
        int used = userProjectRepository.countThisMonthProjects(
                user.getId(), user.getPlanStartedAt(), periodEnd(user));

        if (used < max) return;

        // 유료 플랜이면 크레딧 3개 차감 후 허용
        if (user.getMembership() != User.Membership.basic
                && creditService.getBalance(user.getId()) >= 3) {
            creditService.deduct(user.getId(), projectId, CreditTransaction.CreditType.USE_PROJECT, 3);
            return;
        }

        throw new ApiException(HttpStatus.TOO_MANY_REQUESTS,
                user.getMembership() == User.Membership.basic
                        ? "이번 달 무료 프로젝트를 모두 사용했어요. Premium은 월 3개, Max는 월 10개까지 만들 수 있어요."
                        : "이번 달 프로젝트 " + max + "개를 모두 사용했어요. Max 플랜으로 업그레이드하면 월 10개까지 자유롭게 만들 수 있어요.");
    }

    public void checkRedeployLimit(User user, Long projectId) {
        if (Boolean.TRUE.equals(user.getIsAdmin())) return;

        int max  = getLimits(user)[1];
        int used = redeploymentLogService.countThisMonth(user);

        if (used < max) return;

        // 유료 플랜이면 크레딧 1개 차감 후 허용
        if (user.getMembership() != User.Membership.basic
                && creditService.getBalance(user.getId()) >= 1) {
            creditService.deduct(user.getId(), projectId, CreditTransaction.CreditType.USE_REDEPLOY, 1);
            return;
        }

        throw new ApiException(HttpStatus.TOO_MANY_REQUESTS,
                user.getMembership() == User.Membership.basic
                        ? "Basic 플랜은 월 " + max + "회까지 재배치할 수 있습니다. 업그레이드 후 이용해주세요."
                        : "이번 달 재배치 한도를 초과했습니다. 크레딧을 구매하거나 업그레이드해주세요.");
    }

    public void checkConcurrentLimit(User user) {
        if (Boolean.TRUE.equals(user.getIsAdmin())) return;

        int max  = getLimits(user)[2];
        int used = userProjectRepository.countActiveProjects(user.getId());

        if (used >= max) {
            throw new ApiException(HttpStatus.TOO_MANY_REQUESTS,
                    "동시 작업 한도(" + max + "개)를 초과했습니다. 진행 중인 작업이 완료된 후 시도해주세요.");
        }
    }

    public PlanLimitStatus getLimitStatus(User user) {
        if (Boolean.TRUE.equals(user.getIsAdmin())) {
            return PlanLimitStatus.unlimited(user.getMembership().name());
        }

        int[] limits = getLimits(user);
        int usedProjects  = userProjectRepository.countThisMonthProjects(
                user.getId(), user.getPlanStartedAt(), periodEnd(user));
        int usedRedeploys = redeploymentLogService.countThisMonth(user);
        int usedConcurrent = userProjectRepository.countActiveProjects(user.getId());
        int credits = creditService.getBalance(user.getId());

        return new PlanLimitStatus(
                user.getMembership().name(),
                usedProjects,  limits[0],
                usedRedeploys, limits[1],
                usedConcurrent, limits[2],
                credits
        );
    }
}
