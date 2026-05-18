package com.landup.placement;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PlacementVerificationRepository extends JpaRepository<PlacementVerification, Long> {
    List<PlacementVerification> findAllByPlacementResultId(Long placementResultId);
    List<PlacementVerification> findAllByPlacementResultIdAndSeverity(Long placementResultId,
                                                                     PlacementVerification.Severity severity);
}
