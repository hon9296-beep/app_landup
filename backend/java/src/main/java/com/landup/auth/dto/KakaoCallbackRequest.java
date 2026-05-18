package com.landup.auth.dto;

import lombok.Getter;
import lombok.Setter;

@Getter @Setter
public class KakaoCallbackRequest {
    private String code;
    private String state;
    private String redirectUri;
}
