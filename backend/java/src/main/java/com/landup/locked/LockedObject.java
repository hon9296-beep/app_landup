package com.landup.locked;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;

/**
 * 사용자가 잠근 기물 (locked_object) — 진규 원본 schema (2026-05-09 Entity 신설).
 *
 * 부모: user_projects (1:N). 사용자가 분석 결과 페이지에서 가구 위치 잠그면 이 테이블에 INSERT.
 * 다음 분석 (재배치) 시 잠근 가구는 그대로 유지 (concept_area / placement 단계에서 참조).
 *
 * 그 동안 Java Entity 부재 — string reference 만 (UserProjectService.java, JobInternalController.java).
 * DB 정의는 init_v2.sql line 608-622 에 존재. ORM 사용 시 fail 위험으로 Entity 신설.
 */
@Entity
@Table(name = "locked_object")
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class LockedObject {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userProjectId;

    @Column(nullable = false, length = 64)
    private String objectType;

    @Column(nullable = false)
    private Float centerXMm;

    @Column(nullable = false)
    private Float centerYMm;

    @Column(nullable = false)
    private Float widthMm;

    @Column(nullable = false)
    private Float depthMm;

    @Column(nullable = false)
    private Float heightMm;

    @Column(nullable = false)
    @Builder.Default
    private Float rotationDeg = 0.0f;

    @Column(nullable = false)
    @Builder.Default
    private LocalDateTime lockedAt = LocalDateTime.now();
}
