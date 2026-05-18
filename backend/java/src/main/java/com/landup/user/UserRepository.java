package com.landup.user;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);
    Optional<User> findByPhone(String phone);

    @Query("SELECT u FROM User u WHERE :q = '' OR u.name LIKE %:q% OR u.email LIKE %:q% OR u.phone LIKE %:q%")
    Page<User> searchUsers(@Param("q") String q, Pageable pageable);
}
