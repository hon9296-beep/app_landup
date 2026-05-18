package com.landup.refimage;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/**
 * 레퍼런스 이미지 파일 스트리밍 (dev 전용).
 *
 * S3 업로드 미구현 상태에서 admin 페이지 썸네일 표시용. s3_url=null 인 row 의
 * file_path (예: "references/images/beauty/ref_xxx.jpg") 를 디스크에서 읽어 스트림.
 *
 * 보안: 현재 permitAll 로 열어 둠 (SecurityConfig 매핑). production 전환 시:
 *   - S3 직링크로 교체 (feature/ref-image-s3-integration)
 *   - 또는 /admin 경로 이동 + 프론트가 axios+blob 로 fetch
 *
 * 경로 해석: app.refimage.project-root (default "../..") 기준 entity.filePath 합성.
 *   - bootRun 의 WD 가 backend/java/ 이므로 "../.." = project root
 *   - traversal 방지: resolved path 가 project-root 아래여야 통과
 */
@RestController
@RequestMapping("/refimages")
@RequiredArgsConstructor
public class RefImageFileController {

    private final RefImageRepository repo;

    @Value("${app.refimage.project-root:../..}")
    private String projectRootStr;

    @GetMapping("/{id}")
    public ResponseEntity<FileSystemResource> stream(@PathVariable Long id) {
        RefImage e = repo.findById(id)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
        String filePath = e.getFilePath();
        if (filePath == null || filePath.isBlank()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "file_path empty");
        }

        Path projectRoot = Paths.get(projectRootStr).toAbsolutePath().normalize();
        Path resolved = projectRoot.resolve(filePath).normalize();
        if (!resolved.startsWith(projectRoot)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "path traversal");
        }
        if (!Files.exists(resolved) || !Files.isRegularFile(resolved)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "file not found");
        }

        MediaType ct = guessContentType(resolved.getFileName().toString());
        return ResponseEntity.ok().contentType(ct).body(new FileSystemResource(resolved));
    }

    private MediaType guessContentType(String name) {
        String lower = name.toLowerCase();
        if (lower.endsWith(".png")) return MediaType.IMAGE_PNG;
        if (lower.endsWith(".webp")) return MediaType.parseMediaType("image/webp");
        return MediaType.IMAGE_JPEG;
    }
}
