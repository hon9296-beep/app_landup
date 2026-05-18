package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/brand-categories")
@RequiredArgsConstructor
public class BrandCategoryController {

    private final BrandCategoryService service;

    @GetMapping
    public List<BrandCategory> list() {
        return service.listActive();
    }

    @GetMapping("/{code}")
    public BrandCategory getByCode(@PathVariable String code) {
        return service.getByCode(code);
    }
}
