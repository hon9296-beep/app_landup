package com.landup.file;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * 브랜드 매뉴얼 분석 결과 (영구 자산).
 *
 * 변경 이력:
 *   - 기존 BrandAnalysis 리네임 → brand_manuals
 *   - space_data_json → brand_data_json
 *   - pdf_sha256 추가 → 2026-04-27 UNIQUE 제거
 *   - 2026-04-27 박물관 모델 분리: 원본 필드 (originalFilename/storedFilename/pdfSha256/file_path)
 *     를 BrandArchive 로 이전. 본 테이블은 분석 결과만 보관.
 *   - brand_archive_id (FK SET NULL) 추가 — 원본 추적 (박물관 7일 후 NULL)
 *
 * 라이프사이클: 영구 자산 (참조 0 + 30일 cron). 활성 user_project 참조 중이면 영구.
 */
@Entity
@Table(name = "brand_manuals",
       indexes = {
           @Index(name = "idx_user_status", columnList = "userId,status"),
           @Index(name = "idx_archive", columnList = "brandArchiveId")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BrandManual {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    /** 원본 박물관 추적 (BrandArchive.id). 박물관 7일 후 NULL. */
    private Long brandArchiveId;

    @Column(nullable = false)
    @Builder.Default
    private Integer pageCount = 0;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private ManualStatus status = ManualStatus.processing;

    @Column(columnDefinition = "MEDIUMTEXT")
    private String brandDataJson;

    /** LLM 추출값. NULL 이면 brand_defaults.character_orientation 로 fallback (SQL COALESCE). */
    @Column(length = 20)
    private String characterOrientation;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    public enum ManualStatus { processing, done, error }
}
