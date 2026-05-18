package com.landup.plan;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;

public interface RedeploymentLogRepository extends JpaRepository<RedeploymentLog, Long> {

    @Query("SELECT COUNT(r) FROM RedeploymentLog r WHERE r.userId = :userId " +
           "AND r.createdAt >= :from AND r.createdAt < :to")
    int countThisMonth(@Param("userId") Long userId,
                       @Param("from")   LocalDateTime from,
                       @Param("to")     LocalDateTime to);
}
