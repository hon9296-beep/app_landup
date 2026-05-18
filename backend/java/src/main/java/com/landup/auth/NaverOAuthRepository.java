package com.landup.auth;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

public interface NaverOAuthRepository extends JpaRepository<NaverOAuth, Long> {
    Optional<NaverOAuth> findByNaverId(String naverId);
    boolean existsByUserId(Long userId);
    List<NaverOAuth> findByUserIdIn(Collection<Long> userIds);
}
