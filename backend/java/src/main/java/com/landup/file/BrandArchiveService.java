package com.landup.file;

import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.List;
import java.util.UUID;

/**
 * 브랜드 매뉴얼 원본 박물관 관리 — 2026-04-27 신설.
 *
 * 분석 결과 (BrandManualService) 와 분리:
 *   - 이 서비스: 원본 파일 저장 + 사용자 도면 박물관 페이지 데이터
 *   - BrandManualService: 분석 결과 (brand_data_json) 영구 보관
 *
 * 흐름: 사용자 매뉴얼 업로드 → BrandArchiveService.saveArchive() → archive.id
 *      → BrandManualService.saveBrandManual() (archive.id 받아 stub INSERT)
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BrandArchiveService {

    private final BrandArchiveRepository repo;
    private final S3Service s3Service;

    @Value("${file.upload-dir}")
    private String uploadDir;

    /**
     * 매뉴얼 원본 저장 — 로컬 + S3 둘 다 (2026-04-27 S3 이관).
     * 매번 새 row INSERT (sha256 중복 검출 X).
     *
     * @return 생성된 BrandArchive id
     */
    @Transactional
    public Long saveArchive(Long userId, MultipartFile file) {
        String sha = sha256(file);
        String stored = saveFileToDisk(file);
        String s3Key = s3Service.generateKey("brand-archive", userId, file.getOriginalFilename());
        String s3Url = s3Service.upload(file, s3Key);

        BrandArchive record = BrandArchive.builder()
                .userId(userId)
                .originalFilename(file.getOriginalFilename())
                .storedFilename(stored)
                .s3Url(s3Url)
                .s3Key(s3Key)
                .pdfSha256(sha)
                .fileSizeBytes((int) file.getSize())
                .build();
        return repo.save(record).getId();
    }

    public BrandArchive getOrThrow(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "brand_archive not found: " + id));
    }

    public List<BrandArchive> listByUser(Long userId) {
        return repo.findAllByUserIdOrderByCreatedAtDesc(userId);
    }

    private String saveFileToDisk(MultipartFile file) {
        String stored = UUID.randomUUID().toString().replace("-", "") + "_" + file.getOriginalFilename();
        try {
            Path dir = Paths.get(uploadDir);
            if (!Files.exists(dir)) Files.createDirectories(dir);
            Files.write(dir.resolve(stored), file.getBytes());
        } catch (IOException e) {
            log.warn("[brand_archive] 파일 저장 실패: {}", e.getMessage());
        }
        return stored;
    }

    private String sha256(MultipartFile file) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(file.getBytes());
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "sha256 failed: " + e.getMessage());
        }
    }
}
