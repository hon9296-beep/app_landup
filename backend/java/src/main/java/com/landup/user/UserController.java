package com.landup.user;

import com.landup.auth.GoogleOAuthRepository;
import com.landup.auth.KakaoOAuthRepository;
import com.landup.auth.NaverOAuthRepository;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

/**
 * User 본인 정보 조회/수정 Controller.
 * 로그인/회원가입은 AuthController, 이 파일은 프로필 CRUD만 담당.
 *
 * 신 스키마: joined_at 제거 → 응답에서도 빠짐.
 */
@RestController
@RequestMapping("/me")
@RequiredArgsConstructor
public class UserController {

    private final UserService service;
    private final NaverOAuthRepository naverOAuthRepository;
    private final GoogleOAuthRepository googleOAuthRepository;
    private final KakaoOAuthRepository kakaoOAuthRepository;

    @GetMapping
    public Map<String, Object> getMe(@AuthenticationPrincipal User user) {
        Long userId = user.getId();
        User u = service.getOrThrow(userId);
        String authMethod = "";
        if (naverOAuthRepository.existsByUserId(userId)) authMethod = "네이버 로그인";
        else if (googleOAuthRepository.existsByUserId(userId)) authMethod = "구글 로그인";
        else if (kakaoOAuthRepository.existsByUserId(userId)) authMethod = "카카오 로그인";

        Map<String, Object> resp = new HashMap<>();
        resp.put("id", u.getId());
        resp.put("name", u.getName());
        resp.put("phone", u.getPhone());
        resp.put("email", u.getEmail());
        resp.put("membership", u.getMembership());
        resp.put("isVerified", u.getIsVerified());
        resp.put("authMethod", authMethod);
        resp.put("created_at", u.getCreatedAt());
        resp.put("updated_at", u.getUpdatedAt());
        return resp;
    }

    @PatchMapping
    public User updateProfile(@AuthenticationPrincipal User user,
                              @Valid @RequestBody UpdateProfileRequest body) {
        return service.updateProfile(user.getId(), body);
    }

    @PatchMapping("/membership")
    public User updateMembership(@AuthenticationPrincipal User user,
                                 @RequestBody MembershipBody body) {
        return service.updateMembership(user.getId(), body.membership());
    }

    @DeleteMapping
    public Map<String, Object> delete(@AuthenticationPrincipal User user) {
        service.delete(user.getId());
        return Map.of("deleted", true);
    }

    public record MembershipBody(User.Membership membership) {}
}
