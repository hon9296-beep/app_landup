package com.landup.auth.dto;

import lombok.Getter;
import lombok.Setter;

@Getter @Setter
public class LoginResponse {
    private Long id;
    private String name;
    private String email;
    private String membership;
    private String loginType;
    private String accessToken;                   // JWT Access Token (15분 만료) — 없으면 null
    // Jackson 은 boolean getter isXxx() 를 JSON 키 "xxx" 로 출력 (is- 제거).
    // 프론트는 respectively "requiresProfileCompletion"(false), "admin"(true/false) 로 받음.
    private boolean requiresProfileCompletion;
    private boolean isAdmin;                      // JSON 출력 키: "admin"
    private boolean requiresVerification;         // 이메일 인증 대기 중

    // profile 완성 단기 토큰 — 카카오 callback 응답에만 박힘.
    // 프론트가 ProfileCompletePage 에서 /auth/profile/complete 호출 시 함께 보냄.
    // 5분 만료. 안 보내면 401 → permitAll 보안 hole 차단.
    private String profileToken;

    // 기존 호출자 호환: profileToken 없는 9-인자 생성자 유지.
    public LoginResponse(Long id, String name, String email, String membership,
                         String loginType, String accessToken,
                         boolean requiresProfileCompletion, boolean isAdmin,
                         boolean requiresVerification) {
        this.id = id;
        this.name = name;
        this.email = email;
        this.membership = membership;
        this.loginType = loginType;
        this.accessToken = accessToken;
        this.requiresProfileCompletion = requiresProfileCompletion;
        this.isAdmin = isAdmin;
        this.requiresVerification = requiresVerification;
    }
}
