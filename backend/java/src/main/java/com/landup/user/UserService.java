package com.landup.user;

import com.landup.common.ApiException;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * User 조회/수정 Service — 기존 auth 패키지에 흩어져있던 기본 조회를 분리.
 * 인증·토큰 발급은 여전히 AuthService 가 담당.
 *
 * 신 스키마 반영:
 *   - joined_at 제거
 *   - membership 기본값 free (Entity level)
 */
@Service
@RequiredArgsConstructor
public class UserService {

    private final UserRepository repo;

    public User getOrThrow(Long id) {
        return repo.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "user not found: " + id));
    }

    public User getByEmail(String email) {
        return repo.findByEmail(email)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "user not found: " + email));
    }

    public boolean emailExists(String email) {
        return repo.findByEmail(email).isPresent();
    }

    public boolean phoneExists(String phone) {
        return phone != null && repo.findByPhone(phone).isPresent();
    }

    @Transactional
    public User updateProfile(Long userId, UpdateProfileRequest patch) {
        User u = getOrThrow(userId);
        if (patch.name() != null) u.setName(patch.name());
        if (patch.phone() != null) u.setPhone(patch.phone());
        return repo.save(u);
    }

    @Transactional
    public User updateMembership(Long userId, User.Membership newLevel) {
        // TODO Phase B: 결제/권한 검증 후 호출
        User u = getOrThrow(userId);
        u.setMembership(newLevel);
        return repo.save(u);
    }

    @Transactional
    public void delete(Long userId) {
        // TODO Phase B: 연관 리소스(Pdf/Project/Job) cascade 정책 결정
        if (!repo.existsById(userId)) {
            throw new ApiException(HttpStatus.NOT_FOUND, "user not found: " + userId);
        }
        repo.deleteById(userId);
    }
}
