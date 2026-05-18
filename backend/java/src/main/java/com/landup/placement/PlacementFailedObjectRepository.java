package com.landup.placement;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PlacementFailedObjectRepository extends JpaRepository<PlacementFailedObject, Long> {
    List<PlacementFailedObject> findAllByPlacementResultId(Long placementResultId);
    List<PlacementFailedObject> findAllByObjectType(String objectType);
}
