package com.landup.concept;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;

/**
 * 컨셉 영역 (large 전용) — concept_area.py LLM 결정 결과 영속화 (2026-05-01 신설).
 *
 * 부모: floor_detections (도면 분석 단계에서 생성, placement_result 보다 먼저 영속).
 * 사용처:
 *   - floor_anchors.concept_area_id FK — ref_point 가 어느 영역에 속하는지
 *   - placement_objects.concept_area_id FK — 객체가 어느 영역에 배치됐는지
 *
 * name 은 영문 키 (welcome / photo / experience / screening / retail / checkout / hybrid / lounge).
 * 한국어 라벨은 nodes_large/concept_area.py 의 CONCEPT_AREA_LABEL_KO 매핑 활용.
 *
 * VARCHAR(50) 으로 둠 (ENUM X) — 운영 후 영역 추가/변경 유연성. 어플리케이션 레벨에서 검증.
 */
@Entity
@Table(name = "concept_areas",
       indexes = {
           @Index(name = "idx_concept_floor_detection", columnList = "floorDetectionId"),
           @Index(name = "idx_concept_name", columnList = "name"),
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class ConceptArea {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long floorDetectionId;

    @Column(nullable = false, length = 50)
    private String name;

    @Column(columnDefinition = "TEXT")
    private String polygonJson;

    private Float areaRatio;

    @Column(columnDefinition = "JSON")
    private String targetObjectsJson;

    @Column(nullable = false)
    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();
}
