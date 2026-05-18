package com.landup.auth;

import com.landup.user.User;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * GET /auth/verify?token=xxx — 이메일 인증 토큰 검증 후 JWT 발급.
 */
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class EmailVerificationController {

    private final EmailVerificationService verificationService;
    private final AuthService authService;

    @Value("${jwt.cookie-secure:false}")
    private boolean cookieSecure;

    @GetMapping("/verify")
    public Map<String, Object> verify(@RequestParam String token, HttpServletResponse response) {
        User user = verificationService.verifyToken(token);
        TokenPair pair = authService.issueTokens(user, "email");

        // Refresh Token httpOnly 쿠키 설정
        Cookie cookie = new Cookie("refreshToken", pair.getRefreshToken());
        cookie.setHttpOnly(true);
        cookie.setSecure(cookieSecure);
        cookie.setPath("/api/auth");
        cookie.setMaxAge(7 * 24 * 60 * 60);
        response.addCookie(cookie);

        return Map.of(
                "verified", true,
                "accessToken", pair.getLoginResponse().getAccessToken(),
                "user", Map.of(
                        "id", user.getId(),
                        "name", user.getName(),
                        "email", user.getEmail(),
                        "membership", user.getMembership().name()
                )
        );
    }
}
