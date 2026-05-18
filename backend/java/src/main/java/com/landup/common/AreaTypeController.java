package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/area-types")
@RequiredArgsConstructor
public class AreaTypeController {

    private final AreaTypeService service;

    @GetMapping
    public List<AreaType> list() {
        return service.listActive();
    }

    @GetMapping("/{code}")
    public AreaType getByCode(@PathVariable String code) {
        return service.getByCode(code);
    }
}
