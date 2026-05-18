package com.landup.common;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface BrandCategoryRepository extends JpaRepository<BrandCategory, Long> {
    Optional<BrandCategory> findByCode(String code);
    List<BrandCategory> findAllByIsActiveTrue();
}
