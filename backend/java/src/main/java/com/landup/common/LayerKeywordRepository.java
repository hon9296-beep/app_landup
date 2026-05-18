package com.landup.common;

import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface LayerKeywordRepository extends JpaRepository<LayerKeyword, Long> {
    List<LayerKeyword> findAllByCategoryAndIsActiveTrue(LayerKeyword.LayerCategory category);
}
