package com.landup.refimage;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * init_v2.sql 36번째 테이블 (2026-04-23 신설) — 관리자 레퍼런스 이미지 관리.
 *
 * FK 정책:
 *   userProjectId    — SET NULL (프로젝트 삭제돼도 관리자 자산으로 이미지 보존)
 *   brandCategoryId  — RESTRICT (카테고리 정리 강제)
 *   deletedBy / blacklistedBy — SET NULL (관리자 계정 삭제 시 이력 유지)
 *
 * 블랙리스트: is_blacklisted 플래그 통합 (별도 테이블 없음). sha256 인덱스로 빠른 조회.
 * S3 연동: s3_url 필드만 정의. 실제 업로드 로직은 feature/ref-image-s3-integration 브랜치에서.
 */
@Entity
@Table(name = "ref_image",
    indexes = {
        @Index(name = "idx_category_tier", columnList = "brandCategoryId,floorSizeTier"),
        @Index(name = "idx_sha256_black", columnList = "imageSha256,isBlacklisted"),
        @Index(name = "idx_created", columnList = "createdAt DESC")
    },
    uniqueConstraints = {
        @UniqueConstraint(name = "uq_project_sha", columnNames = {"userProjectId", "imageSha256"})
    }
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImage {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 프로젝트 삭제 시 SET NULL — 이미지는 관리자 자산으로 보존. */
    private Long userProjectId;

    @Column(nullable = false)
    private Long brandCategoryId;

    @Column(nullable = false, length = 64, columnDefinition = "CHAR(64)")
    private String imageSha256;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false,
            columnDefinition = "ENUM('small','medium','large','outdoor')")
    private FloorSizeTier floorSizeTier;

    /** DDG 검색어. 로컬 캐시 유래면 null. */
    @Column(length = 255)
    private String searchKeyword;

    /** 어느 검색 엔진에서 가져왔는지 (2026-04-26 DB 컬럼, 2026-05-09 Entity 추가). */
    @Enumerated(EnumType.STRING)
    @Column(columnDefinition = "ENUM('ddg','pinterest','tavily','manual')")
    private SearchEngine searchEngine;

    /** DDG 원본 URL. 로컬 캐시면 null. */
    @Column(length = 500)
    private String sourceUrl;

    /** S3 production 저장소 URL. null 이면 FE 에서 X 표시. */
    @Column(length = 500)
    private String s3Url;

    /** 로컬 파일 경로 (dev / cache 용). */
    @Column(length = 500)
    private String filePath;

    private Integer fileSizeBytes;

    /** rule-based 참조 경로 텍스트 (예: "DDG 검색 1위 (pinimg.com)"). */
    @Column(length = 500)
    private String refPath;

    /** Vision 분석 점수 0.00~1.00 (이미지 품질 필터 결과, 2026-04-26 DB 컬럼, 2026-05-09 Entity 추가). */
    @Column(precision = 3, scale = 2)
    private java.math.BigDecimal qualityScore;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isDeleted = false;

    @Column(nullable = false)
    @Builder.Default
    private Boolean isBlacklisted = false;

    /** 디자인 채택 횟수 (사용자 선호 학습, 2026-04-26 DB 컬럼, 2026-05-09 Entity 추가). */
    @Column(nullable = false)
    @Builder.Default
    private Integer usedCount = 0;

    /** admin / 사용자 거부 횟수 (2026-04-26 DB 컬럼, 2026-05-09 Entity 추가). */
    @Column(nullable = false)
    @Builder.Default
    private Integer rejectedCount = 0;

    private LocalDateTime deletedAt;
    private Long deletedBy;

    private LocalDateTime blacklistedAt;
    private Long blacklistedBy;

    @Column(nullable = false, updatable = false)
    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum FloorSizeTier { small, medium, large, outdoor }

    public enum SearchEngine { ddg, pinterest, tavily, manual }
}
