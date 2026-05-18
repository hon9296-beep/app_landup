package com.landup.refimage;

import com.landup.common.ApiException;
import com.landup.common.BrandCategory;
import com.landup.common.BrandCategoryRepository;
import com.landup.file.S3Service;
import com.landup.project.UserProject;
import com.landup.project.UserProjectRepository;
import com.landup.refimage.dto.*;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class RefImageService {

    private final RefImageRepository repo;
    private final UserProjectRepository userProjectRepo;
    private final BrandCategoryRepository brandCategoryRepo;
    private final S3Service s3Service;

    @Value("${refimage.base-dir:../storage/refimage}")
    private String refImageBaseDir;

    @Value("${refimage.allowed-extensions:jpg,jpeg,png,webp}")
    private String allowedExtensions;

    @Value("${refimage.max-size-bytes:10485760}")
    private long maxSizeBytes;

    // ── 블랙리스트 체크 (Python internal 호출) ──────────────────────

    @Transactional(readOnly = true)
    public boolean isBlacklisted(String sha256) {
        return repo.existsByImageSha256AndIsBlacklistedTrue(sha256);
    }

    /**
     * 시스템 자동 blacklist 등록 — Python ref_image_analyzer 가 부적절 이미지 (단일
     * 캐릭터 일러스트 / 인물 클로즈업 등) 판정 후 호출. 같은 sha256 의 모든 row 를
     * 동시에 표시 (idempotent).
     *
     * adminUserId=null 로 표시 → "system auto" 의미. Python 측에서 reason 보내면
     * 향후 stat 용. 현재 entity 에 reason 컬럼은 없음 (필요시 추후 추가).
     *
     * 이미 blacklisted 된 row 는 그대로 둠 (덮어쓰지 않아 blacklistedAt / By 보존).
     */
    @Transactional
    public int markBlacklistedBySha256(String sha256, String reason) {
        var rows = repo.findAllByImageSha256(sha256);
        if (rows.isEmpty()) {
            return 0;
        }
        LocalDateTime now = LocalDateTime.now();
        int marked = 0;
        for (RefImage e : rows) {
            if (Boolean.TRUE.equals(e.getIsBlacklisted())) {
                continue;
            }
            e.setIsBlacklisted(true);
            e.setBlacklistedAt(now);
            e.setBlacklistedBy(null);  // null = system auto
            marked++;
        }
        return marked;
    }

    // ── 관리자 리스트 조회 ───────────────────────────────────────

    @Transactional(readOnly = true)
    public Page<RefImageListItem> adminList(
        Long categoryId,
        RefImage.FloorSizeTier tier,
        LocalDateTime fromDate,
        LocalDateTime toDate,
        Pageable pageable
    ) {
        return repo.findForAdmin(categoryId, tier, fromDate, toDate, pageable)
            .map(this::toListItemEnriched);
    }

    @Transactional(readOnly = true)
    public Page<RefImageListItem> listByProject(Long userProjectId, Pageable pageable) {
        return repo.findByUserProjectIdAndIsDeletedFalseOrderByCreatedAtDesc(userProjectId, pageable)
            .map(this::toListItemEnriched);
    }

    /**
     * RefImageListItem.from + user_project lookup 으로 name/createdAt 채움.
     * 같은 페이지 내 동일 user_project_id 가 반복되면 N+1 발생 가능 — 페이지 size 가 작으면(보통 10) 무시.
     * 향후 최적화: user_project_id 모아서 IN 쿼리 1회로 batch lookup.
     */
    private RefImageListItem toListItemEnriched(RefImage e) {
        RefImageListItem item = RefImageListItem.from(e);
        if (e.getUserProjectId() != null) {
            userProjectRepo.findById(e.getUserProjectId()).ifPresent(p -> {
                item.setUserProjectName(p.getName());
                item.setUserProjectCreatedAt(p.getCreatedAt() == null ? null : p.getCreatedAt().toString());
            });
        }
        return item;
    }

    // ── 상세 조회 (세부정보 패널) ───────────────────────────────

    @Transactional(readOnly = true)
    public RefImageDetail detail(Long id) {
        RefImage e = repo.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ref_image not found: " + id));

        String projectName = null;
        if (e.getUserProjectId() != null) {
            projectName = userProjectRepo.findById(e.getUserProjectId())
                .map(UserProject::getName).orElse(null);
        }
        String categoryNameKo = brandCategoryRepo.findById(e.getBrandCategoryId())
            .map(BrandCategory::getNameKo).orElse(null);

        // dev: s3Url 미구현 시 streaming endpoint URL 합성 (RefImageListItem.from 동일 규칙)
        String thumb = e.getS3Url();
        if (thumb == null && e.getFilePath() != null && !e.getFilePath().isBlank() && e.getId() != null) {
            thumb = "/api/refimages/" + e.getId();
        }
        return RefImageDetail.builder()
            .id(e.getId())
            .userProjectId(e.getUserProjectId())
            .userProjectName(projectName)
            .brandCategoryId(e.getBrandCategoryId())
            .brandCategoryNameKo(categoryNameKo)
            .floorSizeTier(e.getFloorSizeTier())
            .searchKeyword(e.getSearchKeyword())
            .sourceUrl(e.getSourceUrl())
            .s3Url(thumb)
            .filePath(e.getFilePath())
            .fileSizeBytes(e.getFileSizeBytes())
            .refPath(e.getRefPath())
            .createdAt(e.getCreatedAt() == null ? null : e.getCreatedAt().toString())
            .isDeleted(e.getIsDeleted())
            .isBlacklisted(e.getIsBlacklisted())
            .build();
    }

    // ── Python → Java 등록 (배치 사이클 종료 시) ───────────────

    /**
     * Python → Java 등록.
     *
     * 2026-04-29: S3 통합 (rendy 가 미리 만들어 둔 구조에 S3 업로드 연결).
     *   image 가 있으면 S3 업로드 → s3Url / refPath 채움.
     *   image null/empty 면 S3 skip — req.refPath 만 그대로 (backwards compat — 기존 호출자 또는 backfill).
     *
     * 동일 (user_project_id, sha256) 재등록은 updateInPlace 로 처리 (UNIQUE 제약).
     */
    @Transactional
    public RefImage create(RefImageCreateRequest req, MultipartFile image) {
        // S3 업로드 (image 있을 때만)
        String s3Url = null;
        String s3Key = req.getRefPath();  // image 없으면 req.refPath fallback
        if (image != null && !image.isEmpty()) {
            Long uidForKey = req.getUserProjectId() != null ? req.getUserProjectId() : 0L;
            s3Key = s3Service.generateKey("ref-image", uidForKey, image.getOriginalFilename());
            s3Url = s3Service.upload(image, s3Key);
        }
        final String _s3Url = s3Url;
        final String _s3Key = s3Key;

        return repo.findByUserProjectIdAndImageSha256(req.getUserProjectId(), req.getImageSha256())
            .map(existing -> updateInPlace(existing, req, _s3Url, _s3Key))
            .orElseGet(() -> repo.save(RefImage.builder()
                .userProjectId(req.getUserProjectId())
                .brandCategoryId(req.getBrandCategoryId())
                .imageSha256(req.getImageSha256())
                .floorSizeTier(req.getFloorSizeTier())
                .searchKeyword(req.getSearchKeyword())
                .sourceUrl(req.getSourceUrl())
                .s3Url(_s3Url)
                .filePath(req.getFilePath())
                .fileSizeBytes(req.getFileSizeBytes())
                .refPath(_s3Key)
                .isDeleted(false)
                .isBlacklisted(false)
                .build()));
    }

    private RefImage updateInPlace(RefImage existing, RefImageCreateRequest req, String s3Url, String s3Key) {
        // 기존 레코드의 메타 갱신 (파일 경로 / 검색어 등)
        existing.setFilePath(req.getFilePath());
        existing.setFileSizeBytes(req.getFileSizeBytes());
        existing.setSearchKeyword(req.getSearchKeyword());
        existing.setSourceUrl(req.getSourceUrl());
        // S3 재업로드 결과는 새 값으로, image 없으면 기존 유지
        if (s3Url != null) existing.setS3Url(s3Url);
        if (s3Key != null) existing.setRefPath(s3Key);
        // is_deleted / is_blacklisted 는 건드리지 않음 (교체가 복구 아님)
        return repo.save(existing);
    }

    // ── 관리자 수정 = 파일 교체 (서버 측 SHA256 계산 — 위변조 방지) ─────────

    @Transactional
    public RefImage replaceFile(Long id, MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "파일이 비어있습니다");
        }
        if (file.getSize() > maxSizeBytes) {
            throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE,
                "파일 크기 초과: " + file.getSize() + " > " + maxSizeBytes);
        }

        // 확장자 검증
        String ext = extractExtension(file.getOriginalFilename());
        Set<String> allowed = Arrays.stream(allowedExtensions.split(","))
            .map(String::trim).map(String::toLowerCase).collect(Collectors.toSet());
        if (!allowed.contains(ext)) {
            throw new ApiException(HttpStatus.UNSUPPORTED_MEDIA_TYPE,
                "지원하지 않는 이미지 확장자: " + ext + " (허용: " + allowed + ")");
        }

        // 기존 레코드 확인 (없으면 일찍 실패 — 디스크 쓰기 전에)
        RefImage e = repo.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ref_image not found: " + id));

        try {
            byte[] bytes = file.getBytes();

            // 서버 측 SHA256 계산 — 클라이언트 보낸 값 신뢰 안 함 (위변조 방지)
            String sha256 = computeSha256(bytes);

            // 디스크 저장
            Path storageDir = Paths.get(refImageBaseDir);
            Files.createDirectories(storageDir);
            String fileName = sha256 + "." + ext;
            Path target = storageDir.resolve(fileName);
            Files.write(target, bytes);

            // entity 갱신 — file_path 는 project root 기준 상대경로 (Python loader 와 일관).
            // refImageBaseDir 는 backend/java cwd 기준이지만, DB 저장은 project root 기준이라야
            // RefImageFileController 가 동일 규칙으로 resolve 가능 (Python 의 references/images/.. 와 같은 기준).
            String relativePath = "backend/storage/refimage/" + fileName;
            e.setImageSha256(sha256);
            e.setFilePath(relativePath);
            e.setFileSizeBytes((int) file.getSize());
            // is_deleted / is_blacklisted 는 건드리지 않음 (교체는 복구 아님)
            return repo.save(e);
        } catch (IOException ioe) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "파일 저장 실패: " + ioe.getMessage());
        }
    }

    private static String extractExtension(String filename) {
        if (filename == null || !filename.contains(".")) return "jpg";  // default
        return filename.substring(filename.lastIndexOf('.') + 1).toLowerCase();
    }

    private static String computeSha256(byte[] bytes) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] hash = md.digest(bytes);
            StringBuilder sb = new StringBuilder(64);
            for (byte b : hash) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (NoSuchAlgorithmException nsae) {
            throw new RuntimeException("SHA-256 미지원 (불가능)", nsae);
        }
    }

    // ── 관리자 삭제 — soft delete (+ 옵션: 블랙리스트 등록) ─────────────
    //
    // blacklist=true: DDG 재다운로드 영구 차단 (Python is_blacklisted 체크).
    //                 "이 sha256 자체가 부적절" 케이스.
    // blacklist=false: row 만 숨김, sha256 은 유효. "이 프로젝트에선 안 쓰지만 다른 곳엔 OK" 케이스.

    @Transactional
    public void softDelete(Long id, Long adminUserId, boolean blacklist) {
        RefImage e = repo.findById(id)
            .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "ref_image not found: " + id));
        LocalDateTime now = LocalDateTime.now();
        e.setIsDeleted(true);
        e.setDeletedAt(now);
        e.setDeletedBy(adminUserId);
        if (blacklist) {
            e.setIsBlacklisted(true);
            e.setBlacklistedAt(now);
            e.setBlacklistedBy(adminUserId);
        }
        repo.save(e);
        // S3 object 제거는 feature/ref-image-s3-integration 에서 S3Service 연동 후 추가
    }
}
