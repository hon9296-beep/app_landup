package com.landup.refimage;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.landup.common.ApiException;
import com.landup.refimage.dto.RefImageCreateRequest;
import jakarta.validation.Valid;
import jakarta.validation.Validator;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Map;
import java.util.stream.Collectors;

/**
 * Python 배치 엔진 (placement-engine:8000) 이 호출하는 내부 API.
 *
 * 외부 사용자에게 노출 금지 — /internal/ prefix + 네트워크 레벨 차단 (k8s NetworkPolicy
 * 또는 Spring Security 에서 내부 IP 범위만 허용) 전제. 현재는 open 상태, 보안 강화는 별도 이슈.
 *
 * 엔드포인트:
 *   POST /internal/ref-images            — 배치 사이클 종료 후 ref 이미지 1개 등록 (S3 업로드 + DB INSERT)
 *   GET  /internal/ref-images/blacklist  — Python 이 DDG 다운로드 전 sha256 블랙리스트 체크
 *   POST /internal/ref-images/blacklist  — Python ref_image_analyzer 가 부적절 판정 후 자동 차단 등록
 *
 * 2026-04-29: multipart 확장 — `payload` (JSON) + `image` (binary, optional).
 *   image 있으면 S3 업로드 + s3Url 채움. image 없으면 S3 skip (backwards compat).
 */
@RestController
@RequestMapping("/internal/ref-images")
@RequiredArgsConstructor
public class RefImageInternalController {

    private final RefImageService service;
    private final ObjectMapper objectMapper;
    private final Validator validator;

    /**
     * 등록 — multipart/form-data:
     *   - payload (JSON string): RefImageCreateRequest
     *   - image (binary, optional): 이미지 파일 — 있으면 S3 업로드, 없으면 skip
     */
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public RefImage create(
        @RequestPart("payload") String payloadJson,
        @RequestPart(value = "image", required = false) MultipartFile image
    ) {
        RefImageCreateRequest req;
        try {
            req = objectMapper.readValue(payloadJson, RefImageCreateRequest.class);
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "payload JSON 파싱 실패: " + e.getMessage());
        }
        // @Valid 동등 — 수동 검증 (multipart 안의 JSON 은 @Valid 자동 적용 안 됨)
        var violations = validator.validate(req);
        if (!violations.isEmpty()) {
            String msg = violations.stream()
                .map(v -> v.getPropertyPath() + " " + v.getMessage())
                .collect(Collectors.joining(", "));
            throw new ApiException(HttpStatus.BAD_REQUEST, "payload 검증 실패: " + msg);
        }
        return service.create(req, image);
    }

    /**
     * Python `ref_image_loader._search_and_save_with_meta` 에서 DDG 결과 저장 전 호출.
     * 반환: {"blacklisted": true/false}
     */
    @GetMapping("/blacklist")
    public Map<String, Boolean> checkBlacklist(@RequestParam String sha256) {
        return Map.of("blacklisted", service.isBlacklisted(sha256));
    }

    /**
     * Python `ref_image_analyzer` 가 Vision LLM 으로 부적절 이미지 (단일 캐릭터 일러스트 /
     * 인물 클로즈업 / 제품 컷 등) 판정 후 호출. 같은 sha256 의 모든 row 를 동시에 차단.
     * 시스템 자동 차단 — blacklistedBy=null 로 표시 (관리자 수동 차단과 구분).
     *
     * 반환: {"marked": N} — 새로 차단된 row 수 (이미 blacklisted 였던 row 는 제외).
     */
    @PostMapping("/blacklist")
    public Map<String, Integer> markBlacklisted(@RequestBody Map<String, String> body) {
        String sha256 = body.get("sha256");
        String reason = body.getOrDefault("reason", "");
        if (sha256 == null || sha256.length() != 64) {
            throw new ApiException(HttpStatus.BAD_REQUEST,
                "sha256 누락 또는 길이 오류 (64 hex 필요): " + (sha256 == null ? "null" : sha256.length()));
        }
        int marked = service.markBlacklistedBySha256(sha256, reason);
        return Map.of("marked", marked);
    }
}
