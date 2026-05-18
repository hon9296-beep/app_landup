package com.landup.user;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 수정판 — joined_at 컬럼 제거됨 (2026-04-20 재설계).
 * 기존 User.java 대체.
 */
@Entity
@Table(name = "users")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class User {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 100)
    private String name;

    @Column(length = 20)
    private String phone;

    @Column(nullable = false, unique = true, length = 255)
    private String email;

    @Column(length = 255)
    private String password;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, columnDefinition = "ENUM('basic','premium','max')")
    @Builder.Default
    private Membership membership = Membership.basic;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isAdmin = false;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isVerified = false;

    @Builder.Default
    private LocalDateTime planStartedAt = LocalDateTime.now();

    @Column(updatable = false)
    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    void onUpdate() { this.updatedAt = LocalDateTime.now(); }

    public enum Membership { basic, premium, max }
}
