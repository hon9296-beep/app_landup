package com.landup.plan;

import com.landup.user.User;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

@Service
@RequiredArgsConstructor
public class RedeploymentLogService {

    private final RedeploymentLogRepository redeploymentLogRepository;

    public void record(Long userId, Long projectId) {
        RedeploymentLog log = RedeploymentLog.builder()
                .userId(userId)
                .projectId(projectId)
                .build();
        redeploymentLogRepository.save(log);
    }

    public int countThisMonth(User user) {
        LocalDateTime from = user.getPlanStartedAt();
        LocalDateTime to   = from.plusMonths(1);
        return redeploymentLogRepository.countThisMonth(user.getId(), from, to);
    }
}
