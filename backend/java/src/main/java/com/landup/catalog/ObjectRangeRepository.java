package com.landup.catalog;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface ObjectRangeRepository extends JpaRepository<ObjectRange, Long> {
    Optional<ObjectRange> findByObjectPaletteIdAndBrandCategory(Long objectPaletteId, String brandCategory);
    List<ObjectRange> findAllByObjectPaletteId(Long objectPaletteId);
}
