package com.landup.refimage.dto;

import com.landup.refimage.RefImage;
import lombok.*;

/**
 * 관리자 리스트 카드용 경량 DTO — 썸네일 + 기본 메타만.
 * 상세 패널은 {@link RefImageDetail} 사용.
 */
@Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
public class RefImageListItem {

    private Long id;
    private Long userProjectId;
    private String userProjectName;        // user_projects.name. 없으면 null. 같은 이름 중복 허용 — 관리자가 created_at 으로 구분
    private String userProjectCreatedAt;   // user_projects.created_at ISO 문자열. 동일명 그룹 구분용
    private String imageSha256;
    private String s3Url;          // null 이면 FE 에서 X 표시
    private String filePath;        // dev fallback
    private RefImage.FloorSizeTier floorSizeTier;
    private String createdAt;       // ref_image 자체 생성 시각 (프로젝트 시각과 다를 수 있음)

    public static RefImageListItem from(RefImage e) {
        // dev: s3Url 미구현 상태에서 file_path 가 있으면 스트리밍 endpoint URL 합성.
        // S3 전환 시 entity.s3Url 그대로 사용 (이 fallback 제거).
        String thumb = e.getS3Url();
        if (thumb == null && e.getFilePath() != null && !e.getFilePath().isBlank() && e.getId() != null) {
            thumb = "/api/refimages/" + e.getId();
        }
        return RefImageListItem.builder()
            .id(e.getId())
            .userProjectId(e.getUserProjectId())
            // userProjectName/CreatedAt 은 service 가 user_project lookup 후 채움 (RefImage 단독으로는 알 수 없음)
            .imageSha256(e.getImageSha256())
            .s3Url(thumb)
            .filePath(e.getFilePath())
            .floorSizeTier(e.getFloorSizeTier())
            .createdAt(e.getCreatedAt() == null ? null : e.getCreatedAt().toString())
            .build();
    }
}
