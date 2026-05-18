package com.landup.placement;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PlacementResultRepository extends JpaRepository<PlacementResult, Long> {
    List<PlacementResult> findAllByFloorDetectionIdOrderByCreatedAtDesc(Long floorDetectionId);
    List<PlacementResult> findAllByStatusOrderByCreatedAtDesc(PlacementResult.ResultStatus status);
}
