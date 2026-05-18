package com.landup.placement;

import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.core.io.ByteArrayResource;

import java.time.Duration;
import java.util.Map;

/**
 * Python FastAPI 호출 클라이언트 — 기존 PlacementClient 구조 유지.
 * 필드명 변경 반영:
 *   - request body 에 floor_archive_id / brand_manual_id / floor_detection_id / placement_result_id 사용
 *     (pdf_file_id → pdf_id → floor_archive_id, 2026-04-27)
 *
 * 타임아웃 5분 (Claude API 호출 포함).
 */
@Component
@RequiredArgsConstructor
public class PlacementClient {

    @Value("${placement.python.base-url:http://worker:8000}")
    private String baseUrl;

    @Value("${internal.api-key:}")
    private String internalApiKey;

    private final RestTemplate restTemplate = buildRestTemplate();

    public Map<String, Object> detect(MultipartFile file, String fileType) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("floor_plan", toResource(file));
        body.add("file_type", fileType);
        return post("/api/detect", body, MediaType.MULTIPART_FORM_DATA);
    }

    public Map<String, Object> brand(MultipartFile file) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("brand_manual", toResource(file));
        return post("/api/brand", body, MediaType.MULTIPART_FORM_DATA);
    }

    public Map<String, Object> spaceData(Map<String, Object> body) {
        return post("/api/space-data", body, MediaType.APPLICATION_JSON);
    }

    public Map<String, Object> place(Map<String, Object> body) {
        return post("/api/place", body, MediaType.APPLICATION_JSON);
    }

    public Map<String, Object> ceilingHeight(MultipartFile file, String fileType) {
        MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
        body.add("cross_section", toResource(file));
        body.add("file_type", fileType);
        return post("/api/ceiling-height", body, MediaType.MULTIPART_FORM_DATA);
    }

    // ==================== 내부 ====================

    @SuppressWarnings("unchecked")
    private Map<String, Object> post(String path, Object body, MediaType contentType) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(contentType);
        if (internalApiKey != null && !internalApiKey.isBlank()) {
            headers.set("X-Internal-Token", internalApiKey);
        }
        HttpEntity<Object> entity = new HttpEntity<>(body, headers);
        return restTemplate.postForObject(baseUrl + path, entity, Map.class);
    }

    private static ByteArrayResource toResource(MultipartFile file) {
        try {
            return new ByteArrayResource(file.getBytes()) {
                @Override
                public String getFilename() { return file.getOriginalFilename(); }
            };
        } catch (Exception e) {
            throw new RuntimeException("multipart file read failed", e);
        }
    }

    private static RestTemplate buildRestTemplate() {
        org.springframework.http.client.SimpleClientHttpRequestFactory f =
                new org.springframework.http.client.SimpleClientHttpRequestFactory();
        f.setConnectTimeout((int) Duration.ofSeconds(30).toMillis());
        f.setReadTimeout((int) Duration.ofMinutes(5).toMillis());
        return new RestTemplate(f);
    }
}
