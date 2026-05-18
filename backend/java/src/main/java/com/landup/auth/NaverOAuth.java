package com.landup.auth;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "naver_oauth")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class NaverOAuth {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false, unique = true, length = 100)
    private String naverId;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String accessToken;

    @Column(columnDefinition = "TEXT")
    private String refreshToken;

    @Column(length = 50)
    @Builder.Default
    private String tokenType = "bearer";

    private LocalDateTime expiresAt;

    @Column(length = 255)
    private String naverEmail;

    @Column(length = 100)
    private String naverNickname;

    @Column(length = 500)
    private String naverProfileImage;

    @Column(length = 50)
    private String naverMobile;

    @Column(columnDefinition = "TEXT")
    private String rawJson;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();
}
