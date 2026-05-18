package com.landup.security;

import io.jsonwebtoken.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Date;

/**
 * JWT Access Token 발급 / 검증
 *
 * - 알고리즘: JWE A256GCM (페이로드 암호화 — jwt.io 등에서 내용 노출 불가)
 * - Access Token 만료: 15분 (application.yml jwt.access-expiry-ms)
 * - subject: userId (Long → String)
 */
@Component
public class JwtProvider {

    private final SecretKey key;
    private final long accessExpiryMs;

    /** application.yml fallback placeholder — prod 에서 이 값이면 부팅 실패. */
    private static final String PLACEHOLDER_SECRET =
            "landup-jwt-secret-key-must-be-at-least-32-characters-long-change-in-prod";

    public JwtProvider(
            @Value("${jwt.secret}") String secret,
            @Value("${jwt.access-expiry-ms}") long accessExpiryMs,
            @Value("${jwt.cookie-secure:false}") boolean cookieSecure
    ) {
        // 보안 가드: prod 식별 = JWT_COOKIE_SECURE=true (HTTPS 강제 환경).
        // 그 환경에서 placeholder secret 그대로면 즉시 부팅 실패 → JWT 위조 방지.
        // (Spring profile 의존 폐기 — 환경별 분기는 환경변수로 통일)
        if (cookieSecure && PLACEHOLDER_SECRET.equals(secret)) {
            throw new IllegalStateException(
                "[SECURITY] prod 환경 (JWT_COOKIE_SECURE=true) 에서 JWT_SECRET 이 placeholder 그대로. " +
                "강한 32자 이상 랜덤 문자열로 교체 후 재배포 필요.");
        }
        if (secret == null || secret.isBlank()) {
            throw new IllegalStateException("[SECURITY] jwt.secret 미설정");
        }
        // SHA-256으로 비밀키를 32바이트로 정규화 → AES-256 키 생성
        try {
            byte[] keyBytes = MessageDigest.getInstance("SHA-256")
                    .digest(secret.getBytes(StandardCharsets.UTF_8));
            this.key = new SecretKeySpec(keyBytes, "AES");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 unavailable", e);
        }
        this.accessExpiryMs = accessExpiryMs;
    }

    /** Access Token 생성 (JWE — 페이로드 암호화) */
    public String generateAccessToken(Long userId) {
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + accessExpiryMs))
                .encryptWith(key, Jwts.KEY.DIRECT, Jwts.ENC.A256GCM)
                .compact();
    }

    /** 토큰에서 userId 추출 (복호화 + 검증 포함) */
    public Long getUserIdFromToken(String token) {
        Claims claims = Jwts.parser()
                .decryptWith(key)
                .build()
                .parseEncryptedClaims(token)
                .getPayload();
        return Long.parseLong(claims.getSubject());
    }

    /** 토큰 유효성 검사 */
    public boolean validateToken(String token) {
        try {
            Jwts.parser().decryptWith(key).build().parseEncryptedClaims(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    // ── 프로필 완성용 단기 토큰 (소셜 로그인 → profile/complete 호출 시 검증용) ──
    // /auth/profile/complete 가 permitAll 이라 누구나 임의 userId 로 호출 가능했음.
    // 카카오 callback 응답에 이 토큰 박아주고, profile/complete 가 토큰 검증 + userId 매칭.

    private static final long PROFILE_TOKEN_EXPIRY_MS = 5 * 60 * 1000L;  // 5분

    /** 프로필 완성용 단기 토큰 (5분, claim type=profile). */
    public String generateProfileToken(Long userId) {
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .claim("type", "profile")
                .issuedAt(new Date())
                .expiration(new Date(System.currentTimeMillis() + PROFILE_TOKEN_EXPIRY_MS))
                .encryptWith(key, Jwts.KEY.DIRECT, Jwts.ENC.A256GCM)
                .compact();
    }

    /** 프로필 토큰 → userId 추출. type=profile 이 아니면 예외. */
    public Long parseProfileToken(String token) {
        if (token == null || token.isBlank()) {
            throw new JwtException("profile token 없음");
        }
        Claims claims = Jwts.parser()
                .decryptWith(key)
                .build()
                .parseEncryptedClaims(token)
                .getPayload();
        if (!"profile".equals(claims.get("type"))) {
            throw new JwtException("profile 토큰 아님 (type 불일치)");
        }
        return Long.parseLong(claims.getSubject());
    }
}
