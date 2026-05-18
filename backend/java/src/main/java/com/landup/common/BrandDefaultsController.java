package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/brand-defaults")
@RequiredArgsConstructor
public class BrandDefaultsController {

    private final BrandDefaultsService service;

    @GetMapping
    public BrandDefaults get() {
        return service.get();
    }

    @PatchMapping
    public BrandDefaults patch(@RequestBody BrandDefaults body) {
        return service.update(body);
    }
}
