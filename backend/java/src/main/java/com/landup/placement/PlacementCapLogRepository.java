package com.landup.placement;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PlacementCapLogRepository extends JpaRepository<PlacementCapLog, Long> {
    List<PlacementCapLog> findAllByPlacementResultId(Long placementResultId);
}
