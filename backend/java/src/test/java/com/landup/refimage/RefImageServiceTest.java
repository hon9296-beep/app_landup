package com.landup.refimage;

import com.landup.common.ApiException;
import com.landup.common.BrandCategory;
import com.landup.common.BrandCategoryRepository;
import com.landup.project.UserProject;
import com.landup.project.UserProjectRepository;
import com.landup.refimage.dto.RefImageCreateRequest;
import com.landup.refimage.dto.RefImageDetail;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * RefImageService 순수 단위 테스트 — Mockito 기반.
 *
 * 프로젝트 기존 Spring context 테스트 infra 에 h2 index 이름 충돌 등
 * 선행 이슈 존재 (별도 수정 필요). 본 브랜치 scope 외라서 통합 테스트 대신
 * Mockito 로 Service 로직 자체만 검증.
 *
 * 검증 범위 (repository / Spring 의존성 제거):
 *   - 블랙리스트 체크 위임
 *   - create: 신규 insert vs 동일 (project, sha256) update
 *   - replaceFile: sha + 경로 갱신, flag 보존
 *   - softDelete: blacklist 옵션 분기 (true=양쪽 플래그, false=delete 만)
 *   - detail: UserProject / BrandCategory 조인 결과 반영
 *   - not found 시 ApiException
 */
@ExtendWith(MockitoExtension.class)
class RefImageServiceTest {

    @Mock RefImageRepository repo;
    @Mock UserProjectRepository userProjectRepo;
    @Mock BrandCategoryRepository brandCategoryRepo;

    @InjectMocks RefImageService service;

    private RefImageCreateRequest baseCreate;

    @BeforeEach
    void setUp() {
        baseCreate = RefImageCreateRequest.builder()
            .userProjectId(10L)
            .brandCategoryId(2L)
            .imageSha256("a".repeat(64))
            .floorSizeTier(RefImage.FloorSizeTier.small)
            .searchKeyword("fashion popup store")
            .sourceUrl("https://pinimg.com/xxx.jpg")
            .filePath("references/images/fashion/ref_a.jpg")
            .fileSizeBytes(102400)
            .refPath("DDG 검색 1위 (pinimg.com)")
            .build();
    }

    // ── 블랙리스트 체크 위임 ─────────────────────────────────────

    @Test
    void isBlacklisted_delegates_to_repo_indexed_lookup() {
        when(repo.existsByImageSha256AndIsBlacklistedTrue("h1")).thenReturn(true);
        when(repo.existsByImageSha256AndIsBlacklistedTrue("h2")).thenReturn(false);

        assertThat(service.isBlacklisted("h1")).isTrue();
        assertThat(service.isBlacklisted("h2")).isFalse();
        verify(repo).existsByImageSha256AndIsBlacklistedTrue("h1");
        verify(repo).existsByImageSha256AndIsBlacklistedTrue("h2");
    }

    // ── create ─────────────────────────────────────────────────

    @Test
    void create_new_image_when_no_existing_pair_sha() {
        when(repo.findByUserProjectIdAndImageSha256(10L, baseCreate.getImageSha256()))
            .thenReturn(Optional.empty());
        when(repo.save(any(RefImage.class)))
            .thenAnswer(inv -> {
                RefImage e = inv.getArgument(0);
                e.setId(100L);
                return e;
            });

        RefImage saved = service.create(baseCreate);

        assertThat(saved.getId()).isEqualTo(100L);
        assertThat(saved.getIsDeleted()).isFalse();
        assertThat(saved.getIsBlacklisted()).isFalse();
        assertThat(saved.getImageSha256()).isEqualTo(baseCreate.getImageSha256());
    }

    @Test
    void create_existing_pair_sha_updates_in_place() {
        RefImage existing = RefImage.builder()
            .id(77L)
            .userProjectId(10L)
            .brandCategoryId(2L)
            .imageSha256("a".repeat(64))
            .floorSizeTier(RefImage.FloorSizeTier.small)
            .filePath("old.jpg")
            .isDeleted(false)
            .isBlacklisted(true) // 이미 블랙리스트 — 교체가 복구 아님을 검증
            .build();
        when(repo.findByUserProjectIdAndImageSha256(10L, "a".repeat(64)))
            .thenReturn(Optional.of(existing));
        when(repo.save(any(RefImage.class))).thenAnswer(inv -> inv.getArgument(0));

        RefImageCreateRequest updateReq = RefImageCreateRequest.builder()
            .userProjectId(10L).brandCategoryId(2L).imageSha256("a".repeat(64))
            .floorSizeTier(RefImage.FloorSizeTier.small)
            .filePath("new.jpg").fileSizeBytes(200000).refPath("로컬 캐시")
            .build();

        RefImage result = service.create(updateReq);

        assertThat(result.getId()).isEqualTo(77L);             // 기존 레코드 보존
        assertThat(result.getFilePath()).isEqualTo("new.jpg"); // 메타 갱신
        assertThat(result.getFileSizeBytes()).isEqualTo(200000);
        assertThat(result.getIsBlacklisted()).isTrue();        // 플래그 유지 (교체 ≠ 복구)
        verify(repo, never()).save(argThat(r -> r.getId() == null));
    }

    // ── replaceFile (multipart, server-side SHA256 계산) ────────

    @TempDir Path tempDir;

    private void wireRefImageBaseDir() {
        // refimage.base-dir 를 임시 디렉토리로 주입
        ReflectionTestUtils.setField(service, "refImageBaseDir", tempDir.toString());
        ReflectionTestUtils.setField(service, "allowedExtensions", "jpg,jpeg,png,webp");
        ReflectionTestUtils.setField(service, "maxSizeBytes", 10_485_760L);
    }

    private static String sha256Hex(byte[] bytes) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        byte[] hash = md.digest(bytes);
        StringBuilder sb = new StringBuilder();
        for (byte b : hash) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    @Test
    void replaceFile_computes_sha_writes_disk_keeps_flags() throws Exception {
        wireRefImageBaseDir();
        byte[] payload = "fake-jpg-content-1234567890".getBytes();
        String expectedSha = sha256Hex(payload);
        MultipartFile file = new MockMultipartFile("file", "newpic.jpg", "image/jpeg", payload);

        RefImage existing = RefImage.builder()
            .id(50L).imageSha256("a".repeat(64))
            .filePath("storage/refimage/old.jpg").fileSizeBytes(100)
            .isDeleted(false).isBlacklisted(true).build();
        when(repo.findById(50L)).thenReturn(Optional.of(existing));
        when(repo.save(any(RefImage.class))).thenAnswer(inv -> inv.getArgument(0));

        RefImage result = service.replaceFile(50L, file);

        // 1. SHA256 서버에서 계산된 값으로 갱신
        assertThat(result.getImageSha256()).isEqualTo(expectedSha);
        // 2. file_path 가 'backend/storage/refimage/{sha}.{ext}' 형태 (project-root 기준)
        assertThat(result.getFilePath()).isEqualTo("backend/storage/refimage/" + expectedSha + ".jpg");
        // 3. 크기 갱신
        assertThat(result.getFileSizeBytes()).isEqualTo(payload.length);
        // 4. flag 보존 (교체 != 복구)
        assertThat(result.getIsDeleted()).isFalse();
        assertThat(result.getIsBlacklisted()).isTrue();
        // 5. 디스크에 실제로 파일 기록됐는지
        Path written = tempDir.resolve(expectedSha + ".jpg");
        assertThat(Files.exists(written)).isTrue();
        assertThat(Files.readAllBytes(written)).isEqualTo(payload);
    }

    @Test
    void replaceFile_unknown_id_throws_404() {
        wireRefImageBaseDir();
        when(repo.findById(999L)).thenReturn(Optional.empty());
        MultipartFile file = new MockMultipartFile("file", "x.jpg", "image/jpeg", "x".getBytes());
        assertThatThrownBy(() -> service.replaceFile(999L, file))
            .isInstanceOf(ApiException.class)
            .hasMessageContaining("999");
    }

    @Test
    void replaceFile_empty_file_throws_400() {
        wireRefImageBaseDir();
        MultipartFile empty = new MockMultipartFile("file", "x.jpg", "image/jpeg", new byte[0]);
        assertThatThrownBy(() -> service.replaceFile(1L, empty))
            .isInstanceOf(ApiException.class)
            .hasMessageContaining("비어");
    }

    @Test
    void replaceFile_unsupported_extension_throws_415() {
        wireRefImageBaseDir();
        // 확장자 체크가 findById 보다 먼저 실행되므로 repo mock 불필요
        MultipartFile bad = new MockMultipartFile("file", "evil.exe", "application/octet-stream", "x".getBytes());
        assertThatThrownBy(() -> service.replaceFile(50L, bad))
            .isInstanceOf(ApiException.class)
            .hasMessageContaining("지원하지 않는");
    }

    // ── softDelete (with optional blacklist) ────────────────────

    @Test
    void softDelete_blacklist_true_sets_both_flags_with_admin_id_and_timestamps() {
        RefImage existing = RefImage.builder()
            .id(60L).isDeleted(false).isBlacklisted(false).build();
        when(repo.findById(60L)).thenReturn(Optional.of(existing));
        when(repo.save(any(RefImage.class))).thenAnswer(inv -> inv.getArgument(0));

        LocalDateTime before = LocalDateTime.now();
        service.softDelete(60L, 42L, true);
        LocalDateTime after = LocalDateTime.now();

        ArgumentCaptor<RefImage> captor = ArgumentCaptor.forClass(RefImage.class);
        verify(repo).save(captor.capture());
        RefImage saved = captor.getValue();

        assertThat(saved.getIsDeleted()).isTrue();
        assertThat(saved.getIsBlacklisted()).isTrue();
        assertThat(saved.getDeletedBy()).isEqualTo(42L);
        assertThat(saved.getBlacklistedBy()).isEqualTo(42L);
        assertThat(saved.getDeletedAt()).isBetween(before, after);
        assertThat(saved.getBlacklistedAt()).isBetween(before, after);
    }

    @Test
    void softDelete_blacklist_false_sets_only_deleted_flag() {
        RefImage existing = RefImage.builder()
            .id(61L).isDeleted(false).isBlacklisted(false).build();
        when(repo.findById(61L)).thenReturn(Optional.of(existing));
        when(repo.save(any(RefImage.class))).thenAnswer(inv -> inv.getArgument(0));

        service.softDelete(61L, 42L, false);

        ArgumentCaptor<RefImage> captor = ArgumentCaptor.forClass(RefImage.class);
        verify(repo).save(captor.capture());
        RefImage saved = captor.getValue();

        assertThat(saved.getIsDeleted()).isTrue();
        assertThat(saved.getDeletedBy()).isEqualTo(42L);
        assertThat(saved.getIsBlacklisted()).isFalse();
        assertThat(saved.getBlacklistedAt()).isNull();
        assertThat(saved.getBlacklistedBy()).isNull();
    }

    @Test
    void softDelete_unknown_id_throws_404() {
        when(repo.findById(999L)).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.softDelete(999L, 1L, true))
            .isInstanceOf(ApiException.class);
    }

    // ── detail with joins ──────────────────────────────────────

    @Test
    void detail_joins_project_name_and_category_name_ko() {
        RefImage e = RefImage.builder()
            .id(1L)
            .userProjectId(10L)
            .brandCategoryId(2L)
            .imageSha256("c".repeat(64))
            .floorSizeTier(RefImage.FloorSizeTier.medium)
            .searchKeyword("test keyword")
            .refPath("DDG 1위")
            .isDeleted(false).isBlacklisted(false)
            .createdAt(LocalDateTime.of(2026, 4, 23, 12, 0))
            .build();
        when(repo.findById(1L)).thenReturn(Optional.of(e));
        when(userProjectRepo.findById(10L)).thenReturn(Optional.of(
            UserProject.builder().id(10L).name("테스트 프로젝트").build()));
        when(brandCategoryRepo.findById(2L)).thenReturn(Optional.of(
            BrandCategory.builder().id(2L).nameKo("패션 브랜드").build()));

        RefImageDetail dto = service.detail(1L);

        assertThat(dto.getId()).isEqualTo(1L);
        assertThat(dto.getUserProjectName()).isEqualTo("테스트 프로젝트");
        assertThat(dto.getBrandCategoryNameKo()).isEqualTo("패션 브랜드");
        assertThat(dto.getSearchKeyword()).isEqualTo("test keyword");
        assertThat(dto.getRefPath()).isEqualTo("DDG 1위");
        assertThat(dto.getFloorSizeTier()).isEqualTo(RefImage.FloorSizeTier.medium);
    }

    @Test
    void detail_when_project_null_leaves_project_name_null() {
        RefImage e = RefImage.builder()
            .id(2L).userProjectId(null).brandCategoryId(2L)
            .imageSha256("d".repeat(64)).floorSizeTier(RefImage.FloorSizeTier.small)
            .isDeleted(false).isBlacklisted(false).build();
        when(repo.findById(2L)).thenReturn(Optional.of(e));
        when(brandCategoryRepo.findById(2L)).thenReturn(Optional.of(
            BrandCategory.builder().nameKo("기타").build()));

        RefImageDetail dto = service.detail(2L);

        assertThat(dto.getUserProjectName()).isNull();
        assertThat(dto.getBrandCategoryNameKo()).isEqualTo("기타");
        verify(userProjectRepo, never()).findById(anyLong());
    }

    @Test
    void detail_unknown_id_throws_404() {
        when(repo.findById(999L)).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service.detail(999L))
            .isInstanceOf(ApiException.class);
    }
}
