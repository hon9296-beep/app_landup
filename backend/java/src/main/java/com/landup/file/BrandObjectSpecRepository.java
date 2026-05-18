package com.landup.file;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface BrandObjectSpecRepository extends JpaRepository<BrandObjectSpec, Long> {
    List<BrandObjectSpec> findAllByBrandManualIdOrderBySeqAsc(Long brandManualId);
    List<BrandObjectSpec> findAllByObjectType(String objectType);
}
