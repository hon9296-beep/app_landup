package com.landup.auth;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface GoogleOAuthRepository extends JpaRepository<GoogleOAuth, Long> {
    Optional<GoogleOAuth> findByGoogleId(String googleId);
    boolean existsByUserId(Long userId);
    List<GoogleOAuth> findByUserIdIn(Collection<Long> userIds);
}
