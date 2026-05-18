package com.landup.file;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 박물관 retention cron — 2026-04-27 신설.
 *
 * 정책:
 *   - floor_archive (도면 원본 박물관) — 7일 retention
 *   - brand_archive (매뉴얼 원본 박물관) — 7일 retention
 *
 * 동작:
 *   - 매일 자정 (00:00) 실행
 *   - 7일 지난 row 의 S3 파일 먼저 삭제 (best effort)
 *   - 그 다음 DB row bulk DELETE
 *   - 분석 결과 (floor_detections / brand_manuals) 의 archive_id FK 는
 *     ON DELETE SET NULL 자동 처리 → 분석 결과 자체는 영구 보존
 *
 * 분석 자산 (floor_detections / brand_manuals) 의 retention 은 별도 cron 으로
 * 추후 구현 (참조 0 + 30일 정책).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ArchiveRetentionScheduler {

    private final FloorArchiveRepository floorArchiveRepo;
    private final BrandArchiveRepository brandArchiveRepo;
    private final S3Service s3Service;

    /** 박물관 보관 기간 (일). 정책 변경 시 이 상수만 수정. */
    private static final int RETENTION_DAYS = 7;

    /**
     * 매일 자정 (00:00:00) 실행.
     * cron 표현: 초 분 시 일 월 요일 → "0 0 0 * * ?"
     */
    @Scheduled(cron = "0 0 0 * * ?")
    @Transactional
    public void cleanupArchive() {
        LocalDateTime cutoff = LocalDateTime.now().minusDays(RETENTION_DAYS);

        // 1. S3 파일 먼저 삭제 (DB DELETE 전에, best effort)
        List<String> floorKeys = floorArchiveRepo.findS3KeysOlderThan(cutoff);
        List<String> brandKeys = brandArchiveRepo.findS3KeysOlderThan(cutoff);
        floorKeys.forEach(s3Service::delete);
        brandKeys.forEach(s3Service::delete);
        log.info("[archive-retention] S3 삭제 — floor {}건, brand {}건", floorKeys.size(), brandKeys.size());

        // 2. DB row bulk DELETE (FK SET NULL 자동 — 분석 결과 영구 보존)
        int floorCount = floorArchiveRepo.deleteOlderThan(cutoff);
        int brandCount = brandArchiveRepo.deleteOlderThan(cutoff);

        log.info("[archive-retention] 박물관 cron 실행 — floor_archive 삭제 {}건, brand_archive 삭제 {}건 (cutoff={})",
                floorCount, brandCount, cutoff);
    }
}
