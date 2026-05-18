package com.landup.file;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface CrossSectionRepository extends JpaRepository<CrossSection, Long> {
    List<CrossSection> findAllByUserIdOrderByCreatedAtDesc(Long userId);
    List<CrossSection> findAllByFloorDetectionId(Long floorDetectionId);
}
