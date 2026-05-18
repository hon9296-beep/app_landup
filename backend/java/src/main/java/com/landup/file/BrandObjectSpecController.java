package com.landup.file;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/brand-object-specs")
@RequiredArgsConstructor
public class BrandObjectSpecController {

    private final BrandObjectSpecService service;

    @GetMapping
    public List<BrandObjectSpec> list(@RequestParam("brand_manual_id") Long brandManualId) {
        return service.listByManual(brandManualId);
    }
}
