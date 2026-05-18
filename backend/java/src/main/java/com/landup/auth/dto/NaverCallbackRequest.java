package com.landup.auth.dto;

import lombok.Getter;
import lombok.Setter;

@Getter @Setter
public class NaverCallbackRequest {
    private String code;
    private String state;
}
