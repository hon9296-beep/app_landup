package com.landup.common;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface AreaTypeRepository extends JpaRepository<AreaType, Long> {
    Optional<AreaType> findByCode(String code);
    List<AreaType> findAllByIsActiveTrueOrderByDisplayOrderAsc();
}
