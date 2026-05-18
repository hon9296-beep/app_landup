package com.landup.auth;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface VerificationTokenRepository extends JpaRepository<VerificationToken, Long> {
    Optional<VerificationToken> findByToken(String token);
    void deleteAllByUserId(Long userId);
    void deleteAllByUserIdAndVerifiedAtIsNull(Long userId);
}
