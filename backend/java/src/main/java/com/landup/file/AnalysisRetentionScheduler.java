package com.landup.file;

import com.landup.floor.FloorDetectionRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * 분석 자산 retention cron — 2026-04-28 신설.
 *
 * 정책 (옵션 1, 단순):
 *   - floor_detections / brand_manuals 의 created_at + 30일 경과
 *   - AND user_projects 어디서도 참조 안 함 (orphan)
 *
 * 자식 row 처리:
 *   - placement_results / placement_objects / floor_anchors 등 → ON DELETE CASCADE 자동
 *   - brand_object_specs → ON DELETE CASCADE 자동
 *
 * cron 시각: 매일 새벽 2시 (박물관 cron 자정과 분리 — 로그 가독성 + 부하 분산).
 *
 * 박물관 cron 과의 차이:
 *   - ArchiveRetentionScheduler: 원본 PDF (floor_archive / brand_archive) 7일 retention
 *   - AnalysisRetentionScheduler: 분석 결과 (floor_detections / brand_manuals) 30일 + 참조 0
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AnalysisRetentionScheduler {

    private final FloorDetectionRepository floorDetectionRepo;
    private final BrandManualRepository brandManualRepo;

    /** 분석 자산 보관 기간 (일). 정책 변경 시 이 상수만 수정. */
    private static final int RETENTION_DAYS = 30;

    /**
     * 매일 새벽 2시 (02:00:00) 실행.
     * cron 표현: 초 분 시 일 월 요일 → "0 0 2 * * ?"
     */
    @Scheduled(cron = "0 0 2 * * ?")
    @Transactional
    public void cleanupOrphanedAnalysis() {
        LocalDateTime cutoff = LocalDateTime.now().minusDays(RETENTION_DAYS);

        int floorCount = floorDetectionRepo.deleteOrphanedOlderThan(cutoff);
        int brandCount = brandManualRepo.deleteOrphanedOlderThan(cutoff);

        log.info("[analysis-retention] 분석 자산 cron 실행 — floor_detections 삭제 {}건, brand_manuals 삭제 {}건 (cutoff={})",
                floorCount, brandCount, cutoff);
    }
}
