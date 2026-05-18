package com.landup.file;

import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.DeleteObjectRequest;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;
import software.amazon.awssdk.services.s3.model.S3Exception;

import java.io.IOException;
import java.util.UUID;

/**
 * AWS S3 업로드/삭제 추상화 — 2026-04-27 신설.
 *
 * 사용처:
 *   - FloorArchiveService.saveFloorArchive() — 도면 원본 업로드
 *   - BrandArchiveService.saveArchive() — 매뉴얼 원본 업로드
 *   - ArchiveRetentionScheduler.cleanupArchive() — 7일 후 S3 파일 삭제
 *
 * URL 정책: S3 default URL "https://{bucket}.s3.amazonaws.com/{key}" 직접 반환.
 * (박물관 PDF 는 사용자별 사적 파일 + 1회성이라 CDN 캐시 효과 없음 → CloudFront 분기 제거)
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class S3Service {

    private final S3Client s3Client;

    @Value("${aws.s3.bucket-name:}")
    private String bucket;

    /**
     * S3 PUT — 파일 업로드 후 외부 노출 URL 반환.
     * 실패 시 ApiException (5xx).
     */
    public String upload(MultipartFile file, String key) {
        if (bucket == null || bucket.isBlank()) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "S3 bucket-name 미설정");
        }
        try {
            PutObjectRequest req = PutObjectRequest.builder()
                    .bucket(bucket)
                    .key(key)
                    .contentType(file.getContentType())
                    .contentLength(file.getSize())
                    .build();
            s3Client.putObject(req, RequestBody.fromBytes(file.getBytes()));
            log.info("[s3] upload OK key={} size={}", key, file.getSize());
            return buildPublicUrl(key);
        } catch (S3Exception | IOException e) {
            log.error("[s3] upload 실패 key={}: {}", key, e.getMessage());
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "S3 upload failed: " + e.getMessage());
        }
    }

    /**
     * S3 DELETE — bucket 안 key 삭제.
     * 실패해도 throw 안 함 (best effort, retention cron 에서 다른 row 처리 계속).
     */
    public void delete(String key) {
        if (key == null || key.isBlank()) return;
        try {
            DeleteObjectRequest req = DeleteObjectRequest.builder()
                    .bucket(bucket)
                    .key(key)
                    .build();
            s3Client.deleteObject(req);
            log.info("[s3] delete OK key={}", key);
        } catch (S3Exception e) {
            log.warn("[s3] delete 실패 key={}: {}", key, e.getMessage());
        }
    }

    /**
     * S3 key 생성 — "{trail}/{userId}/{uuid}_{originalFilename}"
     *
     * @param trail "floor-archive" / "brand-archive" / "ref-image" 등 박물관 trail 구분
     */
    public String generateKey(String trail, Long userId, String originalFilename) {
        String uuid = UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        String safeName = originalFilename == null ? "file" : originalFilename.replaceAll("[\\\\/:*?\"<>|]", "_");
        return String.format("%s/%d/%s_%s", trail, userId, uuid, safeName);
    }

    private String buildPublicUrl(String key) {
        return String.format("https://%s.s3.amazonaws.com/%s", bucket, key);
    }
}
