package com.landup.auth;

import com.landup.auth.dto.LoginResponse;
import lombok.AllArgsConstructor;
import lombok.Getter;

/** Access Token(응답 body) + Refresh Token(쿠키) 묶음 */
@Getter
@AllArgsConstructor
public class TokenPair {
    private final LoginResponse loginResponse;
    private final String refreshToken;  // UUID, httpOnly 쿠키로 전달
}
