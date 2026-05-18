package com.landup.job;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

/**
 * Redis 큐 발행 — 기존 JobPublisher 유지 (스키마 변경 영향 없음).
 * 발행 포맷: LPUSH job_queue {"id": jobId, "type": "...", "params": {...}}
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class JobPublisher {

    private static final String QUEUE_KEY = "job_queue";

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    public void publish(Long jobId, Job.JobType jobType, Map<String, Object> params) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("id", jobId);
        payload.put("type", jobType.name());
        payload.put("params", params);
        try {
            String json = objectMapper.writeValueAsString(payload);
            redis.opsForList().leftPush(QUEUE_KEY, json);
            log.info("[publisher] enqueued job {}", jobId);
        } catch (Exception e) {
            throw new RuntimeException("job publish failed: " + e.getMessage(), e);
        }
    }
}
