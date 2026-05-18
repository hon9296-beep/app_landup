package com.landup.floor;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface FloorAnchorRepository extends JpaRepository<FloorAnchor, Long> {
    List<FloorAnchor> findAllByFloorDetectionId(Long floorDetectionId);
    List<FloorAnchor> findAllByFloorDetectionIdAndScale(Long floorDetectionId, FloorAnchor.Scale scale);
    Optional<FloorAnchor> findByFloorDetectionIdAndAnchorKey(Long floorDetectionId, String anchorKey);
}
