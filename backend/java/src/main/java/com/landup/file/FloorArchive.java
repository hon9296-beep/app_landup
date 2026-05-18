package com.landup.file;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * 도면 원본 박물관 — 2026-04-27 rename (구 Pdf).
 *
 * 박물관 모델:
 *   - 사용자가 업로드한 도면 PDF 보관 (시각적 미리보기)
 *   - 라이프사이클: created_at < NOW() - 7d → cron 자동 삭제
 *
 * 분석 결과는 FloorDetection (auto_detected JSON) 에 별도 영구 보관.
 * FloorDetection.floorArchiveId 가 이 row 를 가리킴 (FK SET NULL — 7일 후 NULL).
 *
 * 변경 이력:
 *   - 기존 PdfFile + PdfPage → pdf 단일 테이블 (pages_json blob)
 *   - 2026-04-27: pdf → floor_archive rename + brand_archive 와 패턴 일관
 */
@Entity
@Table(name = "floor_archive",
       indexes = @Index(name = "idx_user_status", columnList = "userId,status"))
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class FloorArchive {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false, length = 500)
    private String originalFilename;

    @Column(nullable = false, length = 500)
    private String storedFilename;

    /** S3 외부 노출 URL (CloudFront 또는 signed URL). 2026-04-27 추가. */
    @Column(length = 500)
    private String s3Url;

    /** S3 bucket 내부 key (이관/관리용). 2026-04-27 추가. */
    @Column(length = 500)
    private String s3Key;

    @Column(nullable = false)
    @Builder.Default
    private Integer pageCount = 0;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private FloorArchiveStatus status = FloorArchiveStatus.processing;

    @Column(columnDefinition = "MEDIUMTEXT")
    private String pagesJson;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @Builder.Default
    private LocalDateTime createdAt = LocalDateTime.now();

    @Builder.Default
    private LocalDateTime updatedAt = LocalDateTime.now();

    @PreUpdate
    void onUpdate() { this.updatedAt = LocalDateTime.now(); }

    public enum FloorArchiveStatus { processing, done, error }
}
