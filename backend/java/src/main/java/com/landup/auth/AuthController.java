package com.landup.auth;

import com.landup.auth.dto.*;
import com.landup.common.ApiException;
import com.landup.security.JwtProvider;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.web.bind.annotation.*;

import java.time.Duration;
import java.util.Arrays;
import java.util.Map;

/**
 * 인증 엔드포인트
 *
 * POST /auth/signup          → 이메일 회원가입
 * POST /auth/login           → 이메일 로그인
 * POST /auth/naver/callback  → 네이버 OAuth 콜백
 * POST /auth/refresh         → Access Token 갱신 (Refresh Token 쿠키 사용)
 * POST /auth/logout          → 로그아웃 (Refresh Token 삭제)
 */
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;
    private final RefreshTokenRepository refreshTokenRepository;
    private final JwtProvider jwtProvider;

    @Value("${jwt.cookie-secure}")
    private boolean cookieSecure;

    // ── 회원가입 ──────────────────────────────────────────────────────

    @PostMapping("/signup")
    @ResponseStatus(HttpStatus.CREATED)
    public LoginResponse signup(@RequestBody SignUpRequest request) {
        return authService.signup(request);
    }

    // ── 이메일 로그인 ─────────────────────────────────────────────────

    @PostMapping("/login")
    public LoginResponse login(
            @RequestBody LoginRequest request,
            HttpServletResponse response
    ) {
        TokenPair pair = authService.login(request);
        // 이메일 미인증인 경우 refreshToken null — 쿠키 미설정 (카카오 패턴 동일)
        if (pair.getRefreshToken() != null) {
            setRefreshCookie(response, pair.getRefreshToken());
        }
        return pair.getLoginResponse();
    }

    // ── 개발 전용: dev/1234 유저 자동 생성 + 토큰 발급 ─────────────────
    // 로그인 플로우 정리 전 임시. takeover 완료 후 제거.

    @PostMapping("/dev-login")
    public LoginResponse devLogin(HttpServletResponse response) {
        com.landup.user.User user = authService.getOrCreateDevUser();
        TokenPair pair = authService.issueTokens(user, "dev");
        setRefreshCookie(response, pair.getRefreshToken());
        return pair.getLoginResponse();
    }

    // ── 네이버 OAuth 콜백 ─────────────────────────────────────────────

    @PostMapping("/naver/callback")
    public LoginResponse naverCallback(
            @RequestBody NaverCallbackRequest request,
            HttpServletResponse response
    ) {
        TokenPair pair = authService.naverLogin(request);
        if (pair.getRefreshToken() != null) {
            setRefreshCookie(response, pair.getRefreshToken());
        }
        return pair.getLoginResponse();
    }

    // ── Access Token 갱신 ─────────────────────────────────────────────

    @PostMapping("/refresh")
    public Map<String, String> refresh(HttpServletRequest request, HttpServletResponse response) {
        String refreshTokenValue = extractRefreshCookie(request);
        if (refreshTokenValue == null) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "Refresh token이 없습니다.");
        }

        RefreshToken stored = refreshTokenRepository.findById(refreshTokenValue)
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "유효하지 않은 Refresh token입니다."));

        if (stored.isExpired()) {
            refreshTokenRepository.delete(stored);
            clearRefreshCookie(response);
            throw new ApiException(HttpStatus.UNAUTHORIZED, "Refresh token이 만료되었습니다.");
        }

        // Access Token 재발급
        String newAccessToken = jwtProvider.generateAccessToken(stored.getUserId());
        return Map.of("accessToken", newAccessToken);
    }

    // ── 로그아웃 ──────────────────────────────────────────────────────

    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(HttpServletRequest request, HttpServletResponse response) {
        String refreshTokenValue = extractRefreshCookie(request);
        if (refreshTokenValue != null) {
            refreshTokenRepository.deleteById(refreshTokenValue);
        }
        clearRefreshCookie(response);
    }

    // ── 쿠키 유틸 ────────────────────────────────────────────────────

    /**
     * Refresh cookie 박기 — ResponseCookie 사용 (SameSite 명시 가능).
     * 2026-04-28: prod cross-site (frontend=landup.site ↔ backend=api.landup.site) 환경에서
     *   기존 jakarta.Cookie API 는 SameSite 명시 X → 기본값 (Lax) 으로 cross-site cookie 차단 → refresh 실패 → 강제 로그아웃 버그.
     * fix: cookieSecure=true (prod) 면 SameSite=None (cross-site 허용), false (dev) 면 Lax.
     */
    private void setRefreshCookie(HttpServletResponse response, String token) {
        ResponseCookie cookie = ResponseCookie.from("refreshToken", token)
                .httpOnly(true)
                .secure(cookieSecure)
                .path("/api/auth")
                .maxAge(Duration.ofDays(7))
                .sameSite(cookieSecure ? "None" : "Lax")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void clearRefreshCookie(HttpServletResponse response) {
        ResponseCookie cookie = ResponseCookie.from("refreshToken", "")
                .httpOnly(true)
                .secure(cookieSecure)
                .path("/api/auth")
                .maxAge(0)
                .sameSite(cookieSecure ? "None" : "Lax")
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private String extractRefreshCookie(HttpServletRequest request) {
        if (request.getCookies() == null) return null;
        return Arrays.stream(request.getCookies())
                .filter(c -> "refreshToken".equals(c.getName()))
                .map(Cookie::getValue)
                .findFirst()
                .orElse(null);
    }

    @PostMapping("/kakao/callback")
    public LoginResponse kakaoCallback(
            @RequestBody KakaoCallbackRequest request,
            HttpServletResponse response
    ) {
        TokenPair pair = authService.kakaoLogin(request);
        // 프로필 미완성인 경우 refreshToken이 null — 쿠키 미설정
        if (pair.getRefreshToken() != null) {
            setRefreshCookie(response, pair.getRefreshToken());
        }
        return pair.getLoginResponse();
    }

    @PostMapping("/profile/complete")
    public LoginResponse profileComplete(
            @RequestBody ProfileCompleteRequest request,
            HttpServletResponse response
    ) {
        TokenPair pair = authService.completeProfile(request);
        if (pair.getRefreshToken() != null) {
            setRefreshCookie(response, pair.getRefreshToken());
        }
        return pair.getLoginResponse();
    }

    @PostMapping("/google/callback")
    public LoginResponse googleCallback(
            @RequestBody GoogleCallbackRequest request,
            HttpServletResponse response
    ) {
        TokenPair pair = authService.googleLogin(request);
        if (pair.getRefreshToken() != null) {
            setRefreshCookie(response, pair.getRefreshToken());
        }
        return pair.getLoginResponse();
    }
}
