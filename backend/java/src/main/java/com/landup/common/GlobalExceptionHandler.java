package com.landup.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, String>> handleApiException(ApiException e) {
        return ResponseEntity.status(e.getStatus())
                .body(Map.of("detail", e.getMessage()));
    }

    /**
     * Path / Query 파라미터 타입 변환 실패 — 예: /jobs/abc 의 abc → Long 변환 불가.
     * 2026-04-28 추가: 이전엔 catch-all 로 500 반환 → 400 으로 정상화.
     * (TR_D 4-27 [500_jobs_입력검증부재] fix)
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<Map<String, String>> handleTypeMismatch(MethodArgumentTypeMismatchException e) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Map.of("detail", "잘못된 요청 형식: " + e.getName() + " 값을 다시 확인하세요."));
    }

    /**
     * Bean Validation 실패 — DTO 의 @Valid 검증 위반 시.
     * 응답: { detail, errors: { field: msg, ... } } 구조 — 프론트가 필드별 인라인 메시지 표시 가능.
     * 2026-04-28 추가 (TR_D [mypage_저장실패_메시지_모호] fix — 옵션 1).
     */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException e) {
        Map<String, String> fieldErrors = new LinkedHashMap<>();
        for (FieldError fe : e.getBindingResult().getFieldErrors()) {
            // 같은 필드 여러 위반 시 첫 메시지만 (사용자에게 한 줄씩만 노출)
            fieldErrors.putIfAbsent(fe.getField(), fe.getDefaultMessage());
        }
        Map<String, Object> body = new HashMap<>();
        body.put("detail", "입력값을 확인해주세요.");
        body.put("errors", fieldErrors);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> handleGeneral(Exception e) {
        log.error("서버 오류: {}", e.getMessage(), e);
        return ResponseEntity.internalServerError()
                .body(Map.of("detail", "서버 내부 오류가 발생했습니다."));
    }
}
