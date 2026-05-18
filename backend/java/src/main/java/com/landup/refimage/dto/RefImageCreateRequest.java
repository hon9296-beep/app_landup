package com.landup.refimage.dto;

import com.landup.refimage.RefImage;
import jakarta.validation.constraints.*;
import lombok.*;

/**
 * Python handoff 용 생성 요청 — 배치 사이클이 ref 이미지 채택한 직후 Python → Java 호출.
 *
 * S3 업로드는 현재 scope 외 (feature/ref-image-s3-integration).
 * 현재는 file_path (로컬 경로) 와 메타만 저장. s3_url 은 추후 보강.
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImageCreateRequest {

    // 2026-04-27: @NotNull 제거. 파이프라인 신규 등록은 user_project_id 필수지만
    // backfill (디스크 기존 이미지 일괄 적재) 은 프로젝트 무관 → null 허용.
    // 엔티티 컬럼은 이미 nullable (FK SET NULL).
    private Long userProjectId;

    @NotNull
    private Long brandCategoryId;

    @NotBlank
    @Size(min = 64, max = 64)
    private String imageSha256;

    @NotNull
    private RefImage.FloorSizeTier floorSizeTier;

    private String searchKeyword;       // 로컬 캐시면 null 허용
    private String sourceUrl;            // DDG 유래만. 로컬이면 null
    private String filePath;             // references/images/{slug}/ref_xxxx.jpg
    private Integer fileSizeBytes;
    private String refPath;              // rule-based 참조 경로 텍스트
}
