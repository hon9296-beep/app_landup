package com.landup.auth.dto;

import lombok.Getter;
import lombok.Setter;

@Getter @Setter
public class ProfileCompleteRequest {
    private Long userId;
    private String name;
    private String phone;
    private String email;
    /** 카카오 callback 응답에서 받은 5분짜리 단기 토큰. 없으면 401. */
    private String profileToken;
}
