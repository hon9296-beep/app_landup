package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@RequiredArgsConstructor
public class LayerKeywordService {

    private final LayerKeywordRepository repo;

    public List<LayerKeyword> listByCategory(LayerKeyword.LayerCategory category) {
        return repo.findAllByCategoryAndIsActiveTrue(category);
    }
}
