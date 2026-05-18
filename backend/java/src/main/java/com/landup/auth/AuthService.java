package com.landup.auth;

import com.landup.auth.dto.*;
import com.landup.common.ApiException;
import com.landup.security.JwtProvider;
import com.landup.user.User;
import com.landup.user.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.LocalDateTime;
import java.util.Map;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    private final UserRepository userRepository;
    private final NaverOAuthRepository naverOAuthRepository;
    private final KakaoOAuthRepository kakaoOAuthRepository;
    private final GoogleOAuthRepository googleOAuthRepository;
    private final com.fasterxml.jackson.databind.ObjectMapper objectMapper;
    private final RefreshTokenRepository refreshTokenRepository;
    private final JwtProvider jwtProvider;
    private final EmailVerificationService emailVerificationService;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    @Value("${jwt.refresh-expiry-ms}")
    private long refreshExpiryMs;

    @Value("${naver.client-id}")
    private String naverClientId;

    @Value("${naver.client-secret}")
    private String naverClientSecret;

    @Value("${kakao.rest-api-key}")
    private String kakaoRestApiKey;

    @Value("${kakao.client-secret}")
    private String kakaoClientSecret;

    @Value("${google.client-id}")
    private String googleClientId;

    @Value("${google.client-secret}")
    private String googleClientSecret;

    @Value("${google.redirect-uri}")
    private String googleRedirectUri;

    @Value("${kakao.redirect-uri}")
    private String kakaoRedirectUri;

    // ── 개발 전용: dev@local 유저 자동 생성 + 토큰 발급 ────────────────
    // 로그인 플로우 정리 전 임시 엔드포인트. takeover 완료 후 제거.

    @Transactional
    public User getOrCreateDevUser() {
        return userRepository.findByEmail("dev").orElseGet(() -> {
            User u = User.builder()
                    .name("dev")
                    .email("dev")
                    .password(passwordEncoder.encode("1234"))
                    .membership(User.Membership.basic)
                    .isAdmin(true)
                    .build();
            return userRepository.save(u);
        });
    }

    // ── 회원가입 ──────────────────────────────────────────────────────

    @Transactional
    public LoginResponse signup(SignUpRequest req) {
        if (userRepository.findByEmail(req.getEmail()).isPresent()) {
            throw new ApiException(HttpStatus.CONFLICT, "이미 사용 중인 이메일입니다.");
        }
        if (req.getPhone() != null && userRepository.findByPhone(req.getPhone()).isPresent()) {
            throw new ApiException(HttpStatus.CONFLICT, "이미 사용 중인 전화번호입니다.");
        }

        User user = User.builder()
                .name(req.getName())
                .phone(req.getPhone())
                .email(req.getEmail())
                .password(passwordEncoder.encode(req.getPassword()))
                .membership(User.Membership.basic)
                .build();

        userRepository.save(user);

        // 이메일 인증 발송 — JWT는 인증 링크 클릭 후 발급
        emailVerificationService.sendVerificationEmail(user);

        return new LoginResponse(
                user.getId(), user.getName(), user.getEmail(),
                user.getMembership().name(), "email", null, false,
                Boolean.TRUE.equals(user.getIsAdmin()), true);
    }

    // ── 로그인 ────────────────────────────────────────────────────────

    @Transactional
    public TokenPair login(LoginRequest req) {
        User user = userRepository.findByEmail(req.getEmail())
                .orElseThrow(() -> new ApiException(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다."));

        if (user.getPassword() == null || !passwordEncoder.matches(req.getPassword(), user.getPassword())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.");
        }

        // OAuth 와 일관성 — 이메일 미인증이면 메일 재발송 + JWT 미발급
        if (!Boolean.TRUE.equals(user.getIsVerified())) {
            emailVerificationService.sendVerificationEmail(user);
            LoginResponse response = new LoginResponse(
                    user.getId(), user.getName(), user.getEmail(),
                    user.getMembership().name(), "local", null, false,
                    Boolean.TRUE.equals(user.getIsAdmin()), true);
            return new TokenPair(response, null);
        }

        return issueTokens(user, "local");
    }

    // ── 토큰 발급 공통 로직 ───────────────────────────────────────────

    /**
     * Access Token + Refresh Token 생성.
     * 기존 Refresh Token은 재로그인 시 교체(단일 세션).
     *
     * @return TokenPair (LoginResponse + refreshToken UUID)
     */
    @Transactional
    public TokenPair issueTokens(User user, String loginType) {
        // 기존 refresh token 삭제 (단일 세션 정책)
        refreshTokenRepository.deleteAllByUserId(user.getId());

        // Refresh Token 생성 & 저장
        String refreshTokenValue = UUID.randomUUID().toString();
        RefreshToken refreshToken = RefreshToken.builder()
                .token(refreshTokenValue)
                .userId(user.getId())
                .expiresAt(LocalDateTime.now().plusSeconds(refreshExpiryMs / 1000))
                .build();
        refreshTokenRepository.save(refreshToken);

        // Access Token 생성
        String accessToken = jwtProvider.generateAccessToken(user.getId());

        LoginResponse response = new LoginResponse(
                user.getId(), user.getName(), user.getEmail(),
                user.getMembership().name(), loginType, accessToken, false,
                Boolean.TRUE.equals(user.getIsAdmin()), false
        );
        return new TokenPair(response, refreshTokenValue);
    }

    // ── 네이버 OAuth ──────────────────────────────────────────────────

    @Transactional
    public TokenPair naverLogin(NaverCallbackRequest req) {
        WebClient client = WebClient.create();

        // 1. 토큰 발급
        Map tokenRes = client.post()
                .uri("https://nid.naver.com/oauth2.0/token?grant_type=authorization_code"
                        + "&client_id=" + naverClientId
                        + "&client_secret=" + naverClientSecret
                        + "&code=" + req.getCode()
                        + "&state=" + req.getState())
                .retrieve()
                .bodyToMono(Map.class)
                .block();

        if (tokenRes == null || tokenRes.containsKey("error")) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "네이버 토큰 발급 실패");
        }

        String accessToken = (String) tokenRes.get("access_token");
        String refreshToken = (String) tokenRes.get("refresh_token");
        int expiresIn = Integer.parseInt(tokenRes.getOrDefault("expires_in", "3600").toString());

        // 2. 프로필 조회
        Map profileRes = client.get()
                .uri("https://openapi.naver.com/v1/nid/me")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .bodyToMono(Map.class)
                .block();

        if (profileRes == null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "네이버 프로필 조회 실패");
        }

        Map<String, Object> info = (Map<String, Object>) profileRes.get("response");
        String naverId = (String) info.get("id");
        String naverEmail = (String) info.get("email");
        String naverName = info.getOrDefault("name", info.getOrDefault("nickname", "")).toString();
        String naverMobile = info.getOrDefault("mobile", "").toString().replace("-", "");

        if (naverId == null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "네이버 사용자 ID를 가져올 수 없습니다.");
        }

        // 3. DB 처리
        NaverOAuth existing = naverOAuthRepository.findByNaverId(naverId).orElse(null);
        User user;

        if (existing != null) {
            existing.setAccessToken(accessToken);
            existing.setRefreshToken(refreshToken);
            existing.setExpiresAt(LocalDateTime.now().plusSeconds(expiresIn));
            naverOAuthRepository.save(existing);
            user = userRepository.findById(existing.getUserId()).orElseThrow();
        } else {
            user = (naverEmail != null) ? userRepository.findByEmail(naverEmail).orElse(null) : null;

            if (user == null) {
                user = User.builder()
                        .name(naverName.isEmpty() ? "네이버 사용자" : naverName)
                        .phone(naverMobile.isEmpty() ? null : naverMobile)
                        .email(naverEmail != null ? naverEmail : naverId + "@naver.local")
                        .membership(User.Membership.basic)
                        .build();
                userRepository.save(user);
            }

            String rawJson = null;
            try { rawJson = objectMapper.writeValueAsString(profileRes); } catch (Exception ignored) {}

            NaverOAuth oauth = NaverOAuth.builder()
                    .userId(user.getId())
                    .naverId(naverId)
                    .accessToken(accessToken)
                    .refreshToken(refreshToken)
                    .expiresAt(LocalDateTime.now().plusSeconds(expiresIn))
                    .naverEmail(naverEmail)
                    .naverMobile(naverMobile.isEmpty() ? null : naverMobile)
                    .rawJson(rawJson)
                    .build();
            naverOAuthRepository.save(oauth);
        }

        // 이메일 미인증 시 인증 메일 발송 후 JWT 미발급
        if (!Boolean.TRUE.equals(user.getIsVerified())) {
            emailVerificationService.sendVerificationEmail(user);
            LoginResponse response = new LoginResponse(
                    user.getId(), user.getName(), user.getEmail(),
                    user.getMembership().name(), "naver", null, false,
                    Boolean.TRUE.equals(user.getIsAdmin()), true);
            return new TokenPair(response, null);
        }

        return issueTokens(user, "naver");
    }

    // ── 카카오 OAuth ──────────────────────────────────────────────────

    @Transactional
    public TokenPair kakaoLogin(KakaoCallbackRequest req) {
        WebClient client = WebClient.create();

        // 1. 토큰 발급 (application/x-www-form-urlencoded)
        // redirect_uri: 프론트엔드가 실제 사용한 값 우선, 없으면 환경변수 fallback
        String resolvedKakaoRedirectUri = (req.getRedirectUri() != null && !req.getRedirectUri().isBlank())
                ? req.getRedirectUri() : kakaoRedirectUri;

        MultiValueMap<String, String> tokenParams = new LinkedMultiValueMap<>();
        tokenParams.add("grant_type", "authorization_code");
        tokenParams.add("client_id", kakaoRestApiKey);
        tokenParams.add("client_secret", kakaoClientSecret);
        tokenParams.add("redirect_uri", resolvedKakaoRedirectUri);
        tokenParams.add("code", req.getCode());

        Map tokenRes = client.post()
                .uri("https://kauth.kakao.com/oauth/token")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(BodyInserters.fromFormData(tokenParams))
                .retrieve()
                .onStatus(status -> status.isError(), response ->
                        response.bodyToMono(String.class).map(body -> {
                            log.error("[카카오] 토큰 발급 실패 status={} body={}", response.statusCode(), body);
                            return new RuntimeException("카카오 토큰 발급 실패: " + body);
                        })
                )
                .bodyToMono(Map.class)
                .block();

        if (tokenRes == null || tokenRes.containsKey("error")) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "카카오 토큰 발급 실패");
        }

        String accessToken = (String) tokenRes.get("access_token");
        String refreshToken = (String) tokenRes.get("refresh_token");
        int expiresIn = Integer.parseInt(tokenRes.getOrDefault("expires_in", "21600").toString());

        // 2. 프로필 조회
        Map profileRes = client.get()
                .uri("https://kapi.kakao.com/v2/user/me")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .bodyToMono(Map.class)
                .block();

        if (profileRes == null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "카카오 프로필 조회 실패");
        }

        Long kakaoId = ((Number) profileRes.get("id")).longValue();
        Map<String, Object> kakaoAccount = (Map<String, Object>) profileRes.getOrDefault("kakao_account", Map.of());
        Map<String, Object> profile = (Map<String, Object>) kakaoAccount.getOrDefault("profile", Map.of());

        String kakaoEmail = (String) kakaoAccount.get("email");
        String kakaoNickname = (String) profile.getOrDefault("nickname", "카카오 사용자");
        String kakaoProfileImage = (String) profile.get("profile_image_url");

        // 3. DB 처리
        KakaoOAuth existing = kakaoOAuthRepository.findByKakaoId(kakaoId).orElse(null);
        User user;

        if (existing != null) {
            existing.setAccessToken(accessToken);
            existing.setRefreshToken(refreshToken);
            existing.setExpiresAt(LocalDateTime.now().plusSeconds(expiresIn));
            existing.setUpdatedAt(LocalDateTime.now());
            kakaoOAuthRepository.save(existing);
            user = userRepository.findById(existing.getUserId()).orElseThrow();
        } else {
            user = (kakaoEmail != null) ? userRepository.findByEmail(kakaoEmail).orElse(null) : null;

            if (user == null) {
                user = User.builder()
                        .name(kakaoNickname)
                        .email(kakaoEmail != null ? kakaoEmail : kakaoId + "@kakao.local")
                        .membership(User.Membership.basic)
                        .build();
                userRepository.save(user);
            }

            String kakaoRawJson = null;
            try { kakaoRawJson = objectMapper.writeValueAsString(profileRes); } catch (Exception ignored) {}

            KakaoOAuth oauth = KakaoOAuth.builder()
                    .userId(user.getId())
                    .kakaoId(kakaoId)
                    .accessToken(accessToken)
                    .refreshToken(refreshToken)
                    .expiresAt(LocalDateTime.now().plusSeconds(expiresIn))
                    .kakaoEmail(kakaoEmail)
                    .kakaoNickname(kakaoNickname)
                    .kakaoProfileImage(kakaoProfileImage)
                    .rawJson(kakaoRawJson)
                    .build();
            kakaoOAuthRepository.save(oauth);
        }

        boolean requiresProfile = user.getPhone() == null || user.getEmail().endsWith("@kakao.local");
        if (requiresProfile) {
            // 추가 정보 입력 필요 — JWT 미발급, 프로필 완성용 5분 단기 토큰만 발급
            // (profile/complete 가 permitAll 이라 토큰 없으면 누구나 임의 userId 변경 가능 → 차단)
            LoginResponse response = new LoginResponse(
                    user.getId(), user.getName(), user.getEmail(),
                    user.getMembership().name(), "kakao", null, true,
                    Boolean.TRUE.equals(user.getIsAdmin()), false);
            response.setProfileToken(jwtProvider.generateProfileToken(user.getId()));
            return new TokenPair(response, null);
        }

        // 이메일 미인증 시 인증 메일 발송 후 JWT 미발급
        if (!Boolean.TRUE.equals(user.getIsVerified())) {
            emailVerificationService.sendVerificationEmail(user);
            LoginResponse response = new LoginResponse(
                    user.getId(), user.getName(), user.getEmail(),
                    user.getMembership().name(), "kakao", null, false,
                    Boolean.TRUE.equals(user.getIsAdmin()), true);
            return new TokenPair(response, null);
        }

        return issueTokens(user, "kakao");
    }

    // ── 프로필 완성 (소셜 로그인 후 추가 정보 입력) ──────────────────────

    @Transactional
    public TokenPair completeProfile(ProfileCompleteRequest req) {
        // 보안: profileToken 검증 + userId 매칭. 토큰 없거나 위조 / userId 불일치 / 만료 시 401.
        // 카카오 callback 응답에 박힌 5분 단기 토큰만 통과 허용.
        Long tokenUserId;
        try {
            tokenUserId = jwtProvider.parseProfileToken(req.getProfileToken());
        } catch (Exception e) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "프로필 토큰이 유효하지 않습니다.");
        }
        if (!tokenUserId.equals(req.getUserId())) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "프로필 토큰의 userId 가 일치하지 않습니다.");
        }

        User user = userRepository.findById(req.getUserId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "사용자를 찾을 수 없습니다."));

        if (req.getName() != null && !req.getName().isBlank()) {
            user.setName(req.getName());
        }
        if (req.getPhone() != null && !req.getPhone().isBlank()) {
            if (userRepository.findByPhone(req.getPhone()).filter(u -> !u.getId().equals(req.getUserId())).isPresent()) {
                throw new ApiException(HttpStatus.CONFLICT, "이미 사용 중인 전화번호입니다.");
            }
            user.setPhone(req.getPhone());
        }
        if (req.getEmail() != null && !req.getEmail().isBlank()) {
            if (userRepository.findByEmail(req.getEmail()).filter(u -> !u.getId().equals(req.getUserId())).isPresent()) {
                throw new ApiException(HttpStatus.CONFLICT, "이미 사용 중인 이메일입니다.");
            }
            user.setEmail(req.getEmail());
            user.setIsVerified(false);  // 이메일이 변경되면 재인증
        }
        userRepository.save(user);

        // 프로필 완성 후 이메일 인증 발송 — JWT 는 인증 링크 클릭 후 발급
        emailVerificationService.sendVerificationEmail(user);
        LoginResponse response = new LoginResponse(
                user.getId(), user.getName(), user.getEmail(),
                user.getMembership().name(), "kakao", null, false,
                Boolean.TRUE.equals(user.getIsAdmin()), true);
        return new TokenPair(response, null);
    }

    // ── 구글 OAuth ────────────────────────────────────────────────────

    @Transactional
    public TokenPair googleLogin(GoogleCallbackRequest req) {
        WebClient client = WebClient.create();

        // 1. 토큰 발급
        MultiValueMap<String, String> tokenParams = new LinkedMultiValueMap<>();
        // redirect_uri: 프론트엔드가 실제 사용한 값 우선, 없으면 환경변수 fallback
        String resolvedGoogleRedirectUri = (req.getRedirectUri() != null && !req.getRedirectUri().isBlank())
                ? req.getRedirectUri() : googleRedirectUri;

        tokenParams.add("grant_type", "authorization_code");
        tokenParams.add("client_id", googleClientId);
        tokenParams.add("client_secret", googleClientSecret);
        tokenParams.add("redirect_uri", resolvedGoogleRedirectUri);
        tokenParams.add("code", req.getCode());

        Map tokenRes = client.post()
                .uri("https://oauth2.googleapis.com/token")
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(BodyInserters.fromFormData(tokenParams))
                .retrieve()
                .onStatus(status -> status.isError(), response ->
                        response.bodyToMono(String.class).map(body -> {
                            log.error("[구글] 토큰 발급 실패 status={} body={}", response.statusCode(), body);
                            return new RuntimeException("구글 토큰 발급 실패: " + body);
                        })
                )
                .bodyToMono(Map.class)
                .block();

        if (tokenRes == null || tokenRes.containsKey("error")) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "구글 토큰 발급 실패");
        }

        String accessToken = (String) tokenRes.get("access_token");
        String refreshToken = (String) tokenRes.get("refresh_token");
        int expiresIn = Integer.parseInt(tokenRes.getOrDefault("expires_in", "3600").toString());

        // 2. 프로필 조회
        Map profileRes = client.get()
                .uri("https://www.googleapis.com/oauth2/v2/userinfo")
                .header("Authorization", "Bearer " + accessToken)
                .retrieve()
                .bodyToMono(Map.class)
                .block();

        if (profileRes == null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "구글 프로필 조회 실패");
        }

        String googleId    = (String) profileRes.get("id");
        String googleEmail = (String) profileRes.get("email");
        String googleName  = (String) profileRes.getOrDefault("name", "구글 사용자");
        String googlePicture = (String) profileRes.get("picture");

        if (googleId == null) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "구글 사용자 ID를 가져올 수 없습니다.");
        }

        // 3. DB 처리
        GoogleOAuth existing = googleOAuthRepository.findByGoogleId(googleId).orElse(null);
        User user;

        if (existing != null) {
            existing.setAccessToken(accessToken);
            if (refreshToken != null) existing.setRefreshToken(refreshToken);
            existing.setExpiresAt(LocalDateTime.now().plusSeconds(expiresIn));
            existing.setUpdatedAt(LocalDateTime.now());
            googleOAuthRepository.save(existing);
            user = userRepository.findById(existing.getUserId()).orElseThrow();
        } else {
            user = (googleEmail != null) ? userRepository.findByEmail(googleEmail).orElse(null) : null;

            if (user == null) {
                user = User.builder()
                        .name(googleName)
                        .email(googleEmail != null ? googleEmail : googleId + "@google.local")
                        .membership(User.Membership.basic)
                        .build();
                userRepository.save(user);
            }

            String rawJson = null;
            try { rawJson = objectMapper.writeValueAsString(profileRes); } catch (Exception ignored) {}

            GoogleOAuth oauth = GoogleOAuth.builder()
                    .userId(user.getId())
                    .googleId(googleId)
                    .accessToken(accessToken)
                    .refreshToken(refreshToken)
                    .expiresAt(LocalDateTime.now().plusSeconds(expiresIn))
                    .googleEmail(googleEmail)
                    .googleName(googleName)
                    .googleProfileImage(googlePicture)
                    .rawJson(rawJson)
                    .build();
            googleOAuthRepository.save(oauth);
        }

        // 이메일 미인증 시 인증 메일 발송 후 JWT 미발급
        if (!Boolean.TRUE.equals(user.getIsVerified())) {
            emailVerificationService.sendVerificationEmail(user);
            LoginResponse response = new LoginResponse(
                    user.getId(), user.getName(), user.getEmail(),
                    user.getMembership().name(), "google", null, false,
                    Boolean.TRUE.equals(user.getIsAdmin()), true);
            return new TokenPair(response, null);
        }

        return issueTokens(user, "google");
    }
}
