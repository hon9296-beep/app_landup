package com.landup.refimage.dto;

import com.landup.refimage.RefImage;
import lombok.*;

/**
 * 세부정보 패널 전용 DTO — 프론트 화면의 8필드 1:1 매칭.
 *   생성 프로젝트 명 / 카테고리 / 소·중·대·야외 / LLM 검색어 / 사이트 /
 *   LLM 선택 이유 (refPath) / 파일크기 / 생성일
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImageDetail {

    private Long id;
    private Long userProjectId;
    private String userProjectName;      // Service 에서 조인하여 채움
    private Long brandCategoryId;
    private String brandCategoryNameKo;  // Service 에서 조인
    private RefImage.FloorSizeTier floorSizeTier;
    private String searchKeyword;
    private String sourceUrl;
    private String s3Url;
    private String filePath;
    private Integer fileSizeBytes;
    private String refPath;
    private String createdAt;

    private Boolean isDeleted;
    private Boolean isBlacklisted;
}
