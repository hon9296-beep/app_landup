package com.landup.placement;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PlacementObjectRepository extends JpaRepository<PlacementObject, Long> {
    List<PlacementObject> findAllByPlacementResultId(Long placementResultId);
    List<PlacementObject> findAllByPlacementResultIdAndObjectType(Long placementResultId, String objectType);
    List<PlacementObject> findAllByFloorAnchorId(Long floorAnchorId);
}
