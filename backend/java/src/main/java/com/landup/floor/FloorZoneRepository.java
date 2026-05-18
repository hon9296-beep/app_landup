package com.landup.floor;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface FloorZoneRepository extends JpaRepository<FloorZone, Long> {
    List<FloorZone> findAllByFloorDetectionId(Long floorDetectionId);
    Optional<FloorZone> findByFloorDetectionIdAndZoneLabel(Long floorDetectionId, FloorZone.ZoneLabel zoneLabel);
}
