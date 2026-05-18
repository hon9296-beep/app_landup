package com.landup.security;

import com.landup.user.UserRepository;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Spring Security 설정
 *
 * 공개 엔드포인트:
 *   POST /auth/login, /auth/signup, /auth/naver/callback, /auth/kakao/callback
 *   POST /auth/refresh, /auth/logout
 *   GET  /health
 *
 * 그 외 모든 요청: JWT Access Token 필수
 *
 * 필터 순서: RateLimitFilter → JwtAuthenticationFilter → UsernamePasswordAuthenticationFilter
 */
@Configuration
@EnableWebSecurity
@RequiredArgsConstructor
public class SecurityConfig {

    private final JwtProvider jwtProvider;
    private final UserRepository userRepository;
    private final RateLimitFilter rateLimitFilter;

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            // CORS — CorsConfig 빈(WebMvcConfigurer)을 Security 필터 체인에도 적용
            .cors(Customizer.withDefaults())

            // JWT 사용 → CSRF·세션 불필요
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session ->
                    session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))

            // 엔드포인트 접근 제어
            .authorizeHttpRequests(auth -> auth
                    .requestMatchers(
                            "/auth/login",
                            "/auth/signup",
                            "/auth/dev-login",           // 개발 전용 — takeover 완료 후 제거
                            "/auth/naver/callback",
                            "/auth/kakao/callback",
                            "/auth/google/callback",
                            "/auth/profile/complete",
                            "/auth/refresh",
                            "/auth/logout",
                            "/auth/verify",
                            "/health",
                            "/internal/**",
                            "/refimages/**",          // 썸네일 스트리밍 (dev) — S3 전환 시 제거
                            "/brand-categories/**"    // 카테고리 메타 (드롭다운/lookup) — public 메타
                    ).permitAll()
                    .anyRequest().authenticated()
            )

            // 인증 실패 시 401 반환 (기본값이 403이어서 프론트 토큰 갱신 인터셉터가 작동 안 됨)
            .exceptionHandling(ex -> ex
                    .authenticationEntryPoint((req, res, authEx) -> {
                        res.setContentType("application/json;charset=UTF-8");
                        res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                        res.getWriter().write("{\"error\":\"Unauthorized\"}");
                    })
            )

            // JWT 필터 — UsernamePasswordAuthenticationFilter 앞에 배치
            .addFilterBefore(
                    new JwtAuthenticationFilter(jwtProvider, userRepository),
                    UsernamePasswordAuthenticationFilter.class
            )
            // Rate limit 필터 — JWT 필터보다 먼저 실행
            .addFilterBefore(rateLimitFilter, JwtAuthenticationFilter.class);

        return http.build();
    }

    // RateLimitFilter는 @Component라 Spring Boot가 서블릿 필터로 자동 등록하려 함.
    // Security 체인에만 등록하고 싶으므로 자동 등록을 비활성화.
    @Bean
    public FilterRegistrationBean<RateLimitFilter> rateLimitFilterRegistration(RateLimitFilter filter) {
        FilterRegistrationBean<RateLimitFilter> bean = new FilterRegistrationBean<>(filter);
        bean.setEnabled(false);
        return bean;
    }
}
