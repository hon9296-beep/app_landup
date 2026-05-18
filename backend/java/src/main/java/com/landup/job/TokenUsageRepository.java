package com.landup.job;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface TokenUsageRepository extends JpaRepository<TokenUsage, Long> {
    List<TokenUsage> findAllByPlacementResultId(Long placementResultId);
    Optional<TokenUsage> findByPlacementResultIdAndNodeName(Long placementResultId, String nodeName);
    List<TokenUsage> findAllByModel(String model);
}
