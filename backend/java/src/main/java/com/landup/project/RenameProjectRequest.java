package com.landup.project;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * PATCH /projects/{id} 이름 변경 요청 DTO.
 *
 * 검증:
 *   - name: 필수, 1~50자. 빈 값/공백만/50자 초과 거부.
 *
 * 2026-04-28 신설 (TR_D [프로젝트이름_길이제한_없음] / [프로젝트이름_빈값_무반응] fix).
 */
public record RenameProjectRequest(
        @NotBlank(message = "이름을 입력해주세요")
        @Size(max = 50, message = "프로젝트 이름은 50자 이하여야 합니다")
        String name
) {}
