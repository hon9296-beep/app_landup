package com.landup.file;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

/**
 * 브랜드 매뉴얼 원본 박물관 — 2026-04-27 신설.
 *
 * 박물관 모델:
 *   - 사용자가 업로드한 매뉴얼 원본 PDF 보관 (시각적 미리보기 용)
 *   - 라이프사이클: created_at < NOW() - 7d → cron 자동 삭제
 *   - 프로젝트와 무관 (FK 없음, user_id 만)
 *
 * 분석 결과는 BrandManual (분석 자산 trail) 에 별도 영구 보관.
 * BrandManual.brandArchiveId 가 이 row 를 가리킴 (FK SET NULL — 7일 후 NULL).
 */
@Entity
@Table(name = "brand_archive",
       indexes = {
           @Index(name = "idx_user_created", columnList = "userId,createdAt DESC")
       })
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class BrandArchive {

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

    @Column(length = 64)
    private String pdfSha256;

    private Integer fileSizeBytes;

    @Builder.Default
    @Column(nullable = false, updatable = false)
    private LocalDateTime createdAt = LocalDateTime.now();
}
