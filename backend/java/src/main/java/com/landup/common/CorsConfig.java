package com.landup.common;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.Arrays;
import java.util.List;

/**
 * CORS 설정
 *
 * Spring Security가 활성화되면 WebMvcConfigurer의 addCorsMappings는 Security 필터 이후에
 * 적용되어 preflight(OPTIONS)가 차단될 수 있음.
 * → CorsConfigurationSource 빈을 등록하면 SecurityConfig의
 *   .cors(Customizer.withDefaults())가 이 빈을 자동으로 사용.
 *
 * allowCredentials(true): httpOnly 쿠키(Refresh Token) 전송을 위해 필요.
 * ALLOWED_ORIGINS: 쉼표 구분 화이트리스트. 로컬 기본값은 localhost:3000/5173,
 *                  prod에서는 실제 도메인만 열어야 함.
 */
@Configuration
public class CorsConfig {

    @Value("${cors.allowed-origins}")
    private String allowedOriginsRaw;

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        List<String> origins = Arrays.stream(allowedOriginsRaw.split(","))
                .map(String::trim)
                .filter(s -> !s.isBlank())
                .toList();

        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(origins);
        // PATCH 추가 (2026-04-28) — UserController / UserProjectController 등이 PATCH 사용.
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(true);  // httpOnly 쿠키 전송 허용

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }

    /** MVC 레벨 CORS (Security 이전 요청에도 적용) */
    @Bean
    public WebMvcConfigurer corsConfigurer(CorsConfigurationSource corsConfigurationSource) {
        return new WebMvcConfigurer() {};
    }
}
