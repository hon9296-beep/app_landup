package com.landup.refimage.dto;

import jakarta.validation.constraints.*;
import lombok.*;

/**
 * 관리자 "수정 = 재등록 = update" — 이미지 파일 교체만. 메타 변경 불가 (정책).
 *
 * 교체 흐름:
 *   1. 관리자가 드래그앤드롭으로 새 파일 업로드
 *   2. Controller 가 multipart 수신 → 새 sha256 계산
 *   3. 기존 레코드의 파일 교체 (s3 업로드 추후 / 현재는 file_path + sha256 + file_size 갱신)
 *   4. deleted_at / blacklist 등은 유지 — 교체는 복구 아님
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImageUpdateRequest {

    @NotBlank
    @Size(min = 64, max = 64)
    private String newImageSha256;

    private String newFilePath;
    private String newS3Url;       // 추후 S3 연동 후 채워짐
    private Integer newFileSizeBytes;
}
