package com.landup.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Map;

/**
 * 인증 엔드포인트 브루트포스 방어 필터.
 * IP 기준으로 윈도우 내 요청 수를 Redis에 카운트하고, 초과 시 429 반환.
 * Redis 장애 시 fail-open(통과) 처리.
 */
@Component
@RequiredArgsConstructor
public class RateLimitFilter extends OncePerRequestFilter {

    private final RateLimitService rateLimitService;

    @Value("${rate-limit.login.max:10}")
    private int loginMax;
    @Value("${rate-limit.login.window-sec:600}")
    private int loginWindowSec;

    @Value("${rate-limit.signup.max:5}")
    private int signupMax;
    @Value("${rate-limit.signup.window-sec:600}")
    private int signupWindowSec;

    @Value("${rate-limit.refresh.max:20}")
    private int refreshMax;
    @Value("${rate-limit.refresh.window-sec:60}")
    private int refreshWindowSec;

    @Value("${rate-limit.oauth.max:10}")
    private int oauthMax;
    @Value("${rate-limit.oauth.window-sec:600}")
    private int oauthWindowSec;

    private static final Map<String, String> PATH_ACTIONS = Map.of(
            "/auth/login",            "login",
            "/auth/signup",           "signup",
            "/auth/refresh",          "refresh",
            "/auth/naver/callback",   "oauth",
            "/auth/kakao/callback",   "oauth",
            "/auth/google/callback",  "oauth"
    );

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {

        if (!"POST".equals(request.getMethod())) {
            filterChain.doFilter(request, response);
            return;
        }

        String path = stripContextPath(request);
        String action = PATH_ACTIONS.get(path);
        if (action == null) {
            filterChain.doFilter(request, response);
            return;
        }

        String ip = extractIp(request);
        String key = "rl:" + action + ":" + ip;

        int max;
        Duration window;
        switch (action) {
            case "login"   -> { max = loginMax;   window = Duration.ofSeconds(loginWindowSec);   }
            case "signup"  -> { max = signupMax;  window = Duration.ofSeconds(signupWindowSec);  }
            case "refresh" -> { max = refreshMax; window = Duration.ofSeconds(refreshWindowSec); }
            default        -> { max = oauthMax;   window = Duration.ofSeconds(oauthWindowSec);   }
        }

        if (!rateLimitService.isAllowed(key, max, window)) {
            response.setContentType("application/json;charset=UTF-8");
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            response.setHeader("Retry-After", String.valueOf(window.getSeconds()));
            response.getWriter().write("{\"error\":\"Too many requests. Please try again later.\"}");
            return;
        }

        filterChain.doFilter(request, response);
    }

    /** context-path(/api)를 제거해 /auth/login 형태로 정규화. */
    private String stripContextPath(HttpServletRequest request) {
        String uri = request.getRequestURI();
        String ctx = request.getContextPath();
        if (ctx != null && !ctx.isBlank() && uri.startsWith(ctx)) {
            return uri.substring(ctx.length());
        }
        return uri;
    }

    /** X-Forwarded-For가 있으면 첫 번째 IP 사용 (로드밸런서/프록시 환경). */
    private String extractIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            return forwarded.split(",")[0].trim();
        }
        return request.getRemoteAddr();
    }
}
