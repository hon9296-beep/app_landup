package com.landup.catalog;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/catalog")
@RequiredArgsConstructor
public class CatalogController {

    private final CatalogService service;

    @GetMapping("/objects")
    public List<ObjectPalette> listAll() {
        return service.listAll();
    }

    @GetMapping("/objects/{code}")
    public ObjectPalette getByCode(@PathVariable String code) {
        return service.getByCode(code);
    }

    /** 편집 UI용 — 오브젝트 1종의 모든 룰/메타 번들. */
    @GetMapping("/objects/{code}/bundle")
    public Map<String, Object> getBundle(@PathVariable String code) {
        return service.getBundle(code);
    }

    @GetMapping("/aliases/{alias}")
    public ObjectPalette resolveAlias(@PathVariable String alias) {
        return service.resolveByAlias(alias);
    }

    @GetMapping("/pair-rules")
    public List<ObjectPairRule> listPairRules(@RequestParam(value = "source", defaultValue = "vmd_default") ObjectPairRule.Source source) {
        return service.listPairRules(source);
    }
}
