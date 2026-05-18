package com.landup.auth.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter @AllArgsConstructor
public class SignUpResponse {
    private Long id;
    private String name;
    private String email;
    private String membership;
    /** 회원가입 직후 인증 메일 발송됨 → 프론트가 /auth/email-sent 로 navigate */
    private boolean requiresVerification;
}
