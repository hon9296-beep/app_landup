package com.landup.refimage;

import com.landup.refimage.dto.*;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.time.LocalDateTime;

/**
 * 관리자 레퍼런스 이미지 관리 API — /api/admin/ref-images (context-path /api 자동).
 *
 * 보안: admin 권한 체크는 별도 작업 (SecurityConfig / @PreAuthorize 미구현 상태).
 *        현재는 엔드포인트만 열림. feature/admin-security 브랜치에서 추가 예정.
 *
 * 엔드포인트:
 *   GET    /admin/ref-images                  — 리스트 (카테고리/tier/날짜 필터 + 페이지)
 *   GET    /admin/ref-images/by-project/{id}  — 특정 프로젝트의 이미지 (펼치기 시 카드 그리드)
 *   GET    /admin/ref-images/{id}             — 세부정보 패널
 *   PUT    /admin/ref-images/{id}/replace     — 파일 교체 (수정)
 *   DELETE /admin/ref-images/{id}             — soft delete + 블랙리스트
 */
@RestController
@RequestMapping("/admin/ref-images")
@RequiredArgsConstructor
public class RefImageController {

    private final RefImageService service;

    @GetMapping
    public Page<RefImageListItem> list(
        @RequestParam(required = false) Long categoryId,
        @RequestParam(required = false) RefImage.FloorSizeTier tier,
        @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime from,
        @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME) LocalDateTime to,
        @RequestParam(defaultValue = "0") int page,
        @RequestParam(defaultValue = "10") int size
    ) {
        Pageable pageable = PageRequest.of(page, size);
        return service.adminList(categoryId, tier, from, to, pageable);
    }

    @GetMapping("/by-project/{userProjectId}")
    public Page<RefImageListItem> listByProject(
        @PathVariable Long userProjectId,
        @RequestParam(defaultValue = "0") int page,
        @RequestParam(defaultValue = "10") int size
    ) {
        return service.listByProject(userProjectId, PageRequest.of(page, size));
    }

    @GetMapping("/{id}")
    public RefImageDetail detail(@PathVariable Long id) {
        return service.detail(id);
    }

    /**
     * 파일 교체 — multipart/form-data, 필드명 'file'.
     * SHA256 은 서버에서 계산 (위변조 방지). 메타 (사용자 입력) 변경은 정책상 불가.
     */
    @PutMapping(value = "/{id}/replace", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public RefImage replaceFile(
        @PathVariable Long id,
        @RequestParam("file") MultipartFile file
    ) {
        return service.replaceFile(id, file);
    }

    /**
     * 삭제 = soft delete. blacklist 동시 적용 여부는 query param 으로 선택.
     * blacklist=true (default): DDG 재다운로드 영구 차단
     * blacklist=false: row 만 숨김 — sha256 은 유효, 다른 프로젝트에서 재사용 가능
     * 관리자 user_id 는 현재 X-Admin-Id 헤더로 받음 (SecurityConfig 완성 전 임시).
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(
        @PathVariable Long id,
        @RequestHeader(value = "X-Admin-Id", required = false) Long adminUserId,
        @RequestParam(value = "blacklist", defaultValue = "true") boolean blacklist
    ) {
        service.softDelete(id, adminUserId, blacklist);
        return ResponseEntity.noContent().build();
    }
}
