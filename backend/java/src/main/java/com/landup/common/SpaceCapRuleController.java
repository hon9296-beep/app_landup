package com.landup.common;

import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import java.util.List;

@RestController
@RequestMapping("/space-cap-rules")
@RequiredArgsConstructor
public class SpaceCapRuleController {

    private final SpaceCapRuleService service;

    @GetMapping
    public List<SpaceCapRule> list(@RequestParam("scope") String scope,
                                   @RequestParam("kind") SpaceCapRule.KeyKind kind) {
        return service.listByScopeAndKind(scope, kind);
    }

    @GetMapping("/{scope}/{keyName}")
    public SpaceCapRule get(@PathVariable String scope, @PathVariable String keyName) {
        return service.get(scope, keyName);
    }
}
