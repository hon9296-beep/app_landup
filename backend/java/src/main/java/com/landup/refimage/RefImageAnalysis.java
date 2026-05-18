package com.landup.refimage;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * ref_image (원본) 의 LLM Vision 분석 결과 영구 보관 — init_v2.sql 40번째 테이블 (2026-04-29 신설).
 *
 * 분리 이유:
 *   - ref_image 는 admin 페이지 / 검색 / 파일 관리 통합. 분석 JSON 만 별도 테이블에서 영구 보관.
 *   - FK SET NULL: ref_image 삭제돼도 분석 결과 영구 유지 (LLM 디자인 활용은 JSON 만으로 가능).
 *
 * 매칭 카테고리:
 *   - conceptArea: large 영문 키 (welcome/photo/experience/screening/retail/checkout/hybrid/lounge)
 *                  ↔ 한국어 라벨 매핑은 nodes_large/concept_area.py 의 CONCEPT_AREA_LABEL_KO
 *   - brandCategory: 보조 (뷰티/음식/패션 등 기존 brand_categories 와 정합, 보조 카테고리)
 *
 * modelVersion: Vision 모델 변경 시 mismatch → 재분석 invalidation 트리거.
 */
@Entity
@Table(name = "ref_image_analyses",
    indexes = {
        @Index(name = "idx_area",          columnList = "conceptArea"),
        @Index(name = "idx_brand",         columnList = "brandCategory"),
        @Index(name = "idx_ref_image",     columnList = "refImageId"),
        @Index(name = "idx_model_version", columnList = "modelVersion")
    }
)
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImageAnalysis {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** ref_image 삭제 시 SET NULL — 분석 결과는 영구 유지. */
    private Long refImageId;

    /** large 영문 키 (welcome/photo/experience/screening/retail/checkout/hybrid/lounge). */
    @Column(length = 50)
    private String conceptArea;

    /** 보조 카테고리 (뷰티/음식/패션 등). */
    @Column(length = 50)
    private String brandCategory;

    /** 8축 분석 결과 JSON (layout_patterns / partition_usage / focal_points / ...). */
    @Lob
    @Column(columnDefinition = "MEDIUMTEXT")
    private String visionAnalysisJson;

    /** Vision 모델 버전 — mismatch 시 재분석 invalidation. */
    @Column(length = 50)
    private String modelVersion;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false,
            columnDefinition = "ENUM('processing','done','error') DEFAULT 'processing'")
    private Status status;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Column(insertable = false, updatable = false,
            columnDefinition = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    private LocalDateTime createdAt;

    public enum Status {
        processing, done, error
    }
}
