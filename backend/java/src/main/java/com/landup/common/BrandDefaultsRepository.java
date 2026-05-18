package com.landup.common;

import org.springframework.data.jpa.repository.JpaRepository;

public interface BrandDefaultsRepository extends JpaRepository<BrandDefaults, Long> {
    default BrandDefaults getSingleton() {
        return findById(1L).orElseThrow(() -> new IllegalStateException("brand_defaults row(id=1) missing"));
    }
}
