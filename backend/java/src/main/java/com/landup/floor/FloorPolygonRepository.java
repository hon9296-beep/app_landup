package com.landup.floor;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface FloorPolygonRepository extends JpaRepository<FloorPolygon, Long> {
    List<FloorPolygon> findAllByFloorDetectionId(Long floorDetectionId);
    List<FloorPolygon> findAllByFloorDetectionIdAndKind(Long floorDetectionId, FloorPolygon.Kind kind);
}
