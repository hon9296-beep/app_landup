package com.landup.floor;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface FloorPointRepository extends JpaRepository<FloorPoint, Long> {
    List<FloorPoint> findAllByFloorDetectionId(Long floorDetectionId);
    List<FloorPoint> findAllByFloorDetectionIdAndType(Long floorDetectionId, FloorPoint.PointType type);
}
