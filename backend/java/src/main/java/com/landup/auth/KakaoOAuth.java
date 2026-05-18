package com.landup.auth;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "kakao_oauth")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class KakaoOAuth {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false, unique = true)
    private Long kakaoId;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String accessToken;

    @Column(columnDefinition = "TEXT")
    private String refreshToken;

    @Column(length = 50)
    @Builder.Default
    private String tokenType = "bearer";

    private LocalDateTime expiresAt;

    @Column(length = 255)
    private String kakaoEmail;

    @Column(length = 100)
    private String kakaoNickname;

    @Column(length = 500)
    private String kakaoProfileImage;

    @Column(columnDefinition = "TEXT")
    private String rawJson;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();
}
