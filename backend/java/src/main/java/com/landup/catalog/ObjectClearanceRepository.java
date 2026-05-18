package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface ObjectClearanceRepository extends JpaRepository<ObjectClearance, Long> {
    Optional<ObjectClearance> findByObjectPaletteId(Long objectPaletteId);
}
