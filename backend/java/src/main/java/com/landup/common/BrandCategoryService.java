package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@RequiredArgsConstructor
public class BrandCategoryService {

    private final BrandCategoryRepository repo;

    public List<BrandCategory> listActive() {
        return repo.findAllByIsActiveTrue();
    }

    public BrandCategory getByCode(String code) {
        return repo.findByCode(code)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "brand_category not found: " + code));
    }
}
