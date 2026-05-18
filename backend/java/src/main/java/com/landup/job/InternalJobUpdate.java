package com.landup.job;

import java.util.Map;

/**
 * Python worker → Spring /internal/job-update 콜백 payload.
 *
 * 신 스키마 필드명 (구 필드명 주석 병기):
 *   floor_archive_id (구 pdf_id ← pdf_file_id, 2026-04-27 rename)
 *   brand_manual_id  (구 brand_analysis_id)
 *   page_number      (신규 — pdf_page_id 폐기 따라 추가)
 *   progress_stage / progress_pct / progress_message  (구 progress Map 분해)
 *   placement_result_id                                (신규 — place done)
 */
public record InternalJobUpdate(
        Long job_id,
        String status,                 // pending|running|done|error
        String progress_stage,
        Integer progress_pct,
        String progress_message,
        Long result_project_id,
        String error_message,
        Long user_id,
        Long floor_archive_id,         // 2026-04-27 rename: pdf_id → floor_archive_id
        Integer page_number,           // 신규 (pdf_page_id 대체)
        Long brand_manual_id,          // 구 brand_analysis_id
        Long floor_detection_id,
        Long placement_result_id,      // 신규 (place done 시)
        Long project_id,
        Map<String, Object> result     // job_type 별 결과 원문
) {}
