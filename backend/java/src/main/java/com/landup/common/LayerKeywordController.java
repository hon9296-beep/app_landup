package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/layer-keywords")
@RequiredArgsConstructor
public class LayerKeywordController {

    private final LayerKeywordService service;

    @GetMapping
    public List<LayerKeyword> list(@RequestParam("category") LayerKeyword.LayerCategory category) {
        return service.listByCategory(category);
    }
}
