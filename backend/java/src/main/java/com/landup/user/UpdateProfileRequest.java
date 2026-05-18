package com.landup.user;

import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

/**
 * /me PATCH 요청 DTO. 둘 다 nullable — null 이면 해당 필드 변경 안 함.
 *
 * 검증:
 *   - name: 빈 문자열("") 거부. null 은 통과 (변경 의사 없음)
 *   - phone: 10~11자리 숫자만. null 은 통과
 *
 * 2026-04-28 신설 (TR_D [mypage_저장실패_메시지_모호] fix — 옵션 1 필드별 errors 응답).
 */
public record UpdateProfileRequest(
        @Size(min = 1, message = "이름을 입력해주세요") String name,
        @Pattern(regexp = "^[0-9]{10,11}$", message = "전화번호는 10~11자리 숫자여야 합니다") String phone
) {}
