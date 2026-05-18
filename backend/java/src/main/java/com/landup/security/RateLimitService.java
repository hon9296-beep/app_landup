package com.landup.security;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;

@Slf4j
@Service
@RequiredArgsConstructor
public class RateLimitService {

    private final StringRedisTemplate stringRedisTemplate;

    /**
     * 요청 허용 여부. Redis 장애 시 fail-open(허용)으로 처리해 서비스 중단 방지.
     *
     * @param key    Redis 키 (예: "rl:login:1.2.3.4")
     * @param max    윈도우 내 최대 허용 횟수
     * @param window 윈도우 크기
     */
    public boolean isAllowed(String key, int max, Duration window) {
        try {
            Long count = stringRedisTemplate.opsForValue().increment(key);
            if (count != null && count == 1) {
                stringRedisTemplate.expire(key, window);
            }
            return count == null || count <= max;
        } catch (Exception e) {
            log.warn("Redis rate-limit 조회 실패 — fail-open: {}", e.getMessage());
            return true;
        }
    }
}
