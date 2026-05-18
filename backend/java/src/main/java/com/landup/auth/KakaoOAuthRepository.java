package com.landup.auth;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface KakaoOAuthRepository extends JpaRepository<KakaoOAuth, Long> {
    Optional<KakaoOAuth> findByKakaoId(Long kakaoId);
    boolean existsByUserId(Long userId);
    List<KakaoOAuth> findByUserIdIn(Collection<Long> userIds);
}
